"""Translator — Dịch văn bản sử dụng API tương thích OpenAI (DeepSeek).

Tích hợp API dịch thuật, gộp các block của trang để dịch trong 1 request,
và xử lý rate limits, định dạng trả về, retry/fallback.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
import openai

from pdf_translator.models import AppConfig, TextBlock, TranslatedBlock
from pdf_translator.logger import get_logger
from pdf_translator.cache import TranslationCache

logger = get_logger(__name__)

# Thư mục gốc dự án và đường dẫn file cache mặc định
_THIS_DIR = Path(__file__).parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
DEFAULT_CACHE_PATH = _PROJECT_ROOT / ".translation_cache.db"


class Translator:
    """Quản lý việc gọi API dịch và map kết quả dịch về từng TextBlock."""

    def __init__(self, config: AppConfig) -> None:
        """Khởi tạo Translator.

        Args:
            config: Cấu hình ứng dụng AppConfig.
        """
        # Hỗ trợ API Key trống cho các trường hợp chạy test mock
        self.client = openai.AsyncOpenAI(
            api_key=config.api_key or "mock-key",
            base_url=config.api_base_url,
        )
        self.model = config.model
        self.semaphore = asyncio.Semaphore(config.concurrency)
        self.use_cache = config.use_cache
        self.source_lang = config.source_lang
        self.target_lang = config.target_lang
        self.cache = TranslationCache(DEFAULT_CACHE_PATH)

    async def translate_page(
        self, blocks: list[TextBlock]
    ) -> list[TranslatedBlock]:
        """Dịch toàn bộ các text blocks trên một trang.

        Gộp tất cả các block chưa dịch (uncached) của trang để dịch trong 1 request
        nhằm tối ưu chi phí và giữ ngữ cảnh liền mạch.

        Args:
            blocks: Danh sách TextBlock cần dịch.

        Returns:
            Danh sách các TranslatedBlock đã được dịch.
        """
        if not blocks:
            return []

        cached_translations: dict[int, str] = {}
        uncached_blocks: list[TextBlock] = []
        uncached_indices: list[int] = []

        if self.use_cache:
            for i, block in enumerate(blocks):
                cached = self.cache.get(
                    block.text, self.source_lang, self.target_lang, self.model
                )
                if cached:
                    cached_translations[i] = cached
                else:
                    uncached_blocks.append(block)
                    uncached_indices.append(i)
        else:
            uncached_blocks = blocks
            uncached_indices = list(range(len(blocks)))

        # Nếu tất cả các block đã nằm trong cache
        if not uncached_blocks:
            logger.debug(
                f"Trang {blocks[0].page_number}: Nạp thành công tất cả {len(blocks)} blocks từ cache."
            )
            return [
                TranslatedBlock(
                    original=blocks[i],
                    translated_text=cached_translations[i],
                    adjusted_font_size=blocks[i].font_size,
                )
                for i in range(len(blocks))
            ]

        prompt = self._build_prompt(uncached_blocks)
        system_prompt = self._get_system_prompt()

        async with self.semaphore:
            try:
                response = await self._call_api(system_prompt, prompt)
                parsed_map = self._parse_response(response, uncached_blocks)

                # Kiểm tra xem có đủ tất cả các block không
                if all(i in parsed_map for i in range(len(uncached_blocks))):
                    if self.use_cache:
                        for idx, text_translated in parsed_map.items():
                            orig_idx = uncached_indices[idx]
                            self.cache.set(
                                blocks[orig_idx].text,
                                text_translated,
                                self.source_lang,
                                self.target_lang,
                                self.model,
                            )

                    result: list[TranslatedBlock] = []
                    for i in range(len(blocks)):
                        if i in cached_translations:
                            text = cached_translations[i]
                        else:
                            uncached_idx = uncached_indices.index(i)
                            text = parsed_map[uncached_idx]
                        result.append(
                            TranslatedBlock(
                                original=blocks[i],
                                translated_text=text,
                                adjusted_font_size=blocks[i].font_size,
                            )
                        )
                    return result

                logger.warning(
                    f"Kết quả dịch thiếu block hoặc sai định dạng trên trang {blocks[0].page_number}. "
                    f"Đang thực hiện dịch lại với chỉ dẫn chặt chẽ hơn..."
                )
            except Exception as e:
                logger.warning(
                    f"Lỗi khi gọi API dịch trên trang {blocks[0].page_number}: {e}. "
                    f"Đang thực hiện dịch lại..."
                )
                parsed_map = {}

            # Retry 1 lần với strict system prompt
            strict_system_prompt = (
                self._get_system_prompt()
                + "\n\nCRITICAL: You must return exactly the same number of translation blocks as the input. "
                "Do not omit any numbers. Do not add any explanations or notes. "
                "Format each output block starting with the correct index bracket: [index] translation text."
            )
            try:
                response = await self._call_api(strict_system_prompt, prompt)
                new_parsed_map = self._parse_response(response, uncached_blocks)
                combined_map = {**parsed_map, **new_parsed_map}

                if all(i in combined_map for i in range(len(uncached_blocks))):
                    if self.use_cache:
                        for idx, text_translated in combined_map.items():
                            orig_idx = uncached_indices[idx]
                            self.cache.set(
                                blocks[orig_idx].text,
                                text_translated,
                                self.source_lang,
                                self.target_lang,
                                self.model,
                            )

                    result = []
                    for i in range(len(blocks)):
                        if i in cached_translations:
                            text = cached_translations[i]
                        else:
                            uncached_idx = uncached_indices.index(i)
                            text = combined_map[uncached_idx]
                        result.append(
                            TranslatedBlock(
                                original=blocks[i],
                                translated_text=text,
                                adjusted_font_size=blocks[i].font_size,
                            )
                        )
                    return result

                logger.error(
                    f"Dịch lại trang {blocks[0].page_number} vẫn thất bại hoặc thiếu block. "
                    f"Sẽ dùng cơ chế fallback giữ nguyên văn bản gốc cho các block thiếu."
                )

                if self.use_cache:
                    for idx, text_translated in combined_map.items():
                        orig_idx = uncached_indices[idx]
                        self.cache.set(
                            blocks[orig_idx].text,
                            text_translated,
                            self.source_lang,
                            self.target_lang,
                            self.model,
                        )

                result = []
                for i in range(len(blocks)):
                    if i in cached_translations:
                        text = cached_translations[i]
                    else:
                        uncached_idx = uncached_indices.index(i)
                        text = combined_map.get(uncached_idx, blocks[i].text)
                    result.append(
                        TranslatedBlock(
                            original=blocks[i],
                            translated_text=text,
                            adjusted_font_size=blocks[i].font_size,
                        )
                    )
                return result
            except Exception as e:
                # Nếu lần 2 bị lỗi nhưng lần 1 đã có một số kết quả, vẫn cố gắng dùng kết quả lần 1
                if parsed_map:
                    logger.warning(
                        f"Lỗi khi gọi API dịch lại trên trang {blocks[0].page_number}: {e}. "
                        f"Sẽ sử dụng kết quả dịch bán phần từ lần gọi đầu tiên."
                    )
                    if self.use_cache:
                        for idx, text_translated in parsed_map.items():
                            orig_idx = uncached_indices[idx]
                            self.cache.set(
                                blocks[orig_idx].text,
                                text_translated,
                                self.source_lang,
                                self.target_lang,
                                self.model,
                            )

                    result = []
                    for i in range(len(blocks)):
                        if i in cached_translations:
                            text = cached_translations[i]
                        else:
                            uncached_idx = uncached_indices.index(i)
                            text = parsed_map.get(uncached_idx, blocks[i].text)
                        result.append(
                            TranslatedBlock(
                                original=blocks[i],
                                translated_text=text,
                                adjusted_font_size=blocks[i].font_size,
                            )
                        )
                    return result
                # Nếu cả 2 lần đều lỗi hoàn toàn, ném ngoại lệ lên bộ điều phối
                logger.error(
                    f"Thất bại hoàn toàn khi dịch trang {blocks[0].page_number}: {e}"
                )
                raise e

    def _get_system_prompt(self) -> str:
        """Trả về system prompt chuẩn cho LLM dịch."""
        return (
            "You are a professional English to Vietnamese translator.\n"
            "Translate the following text blocks precisely into natural Vietnamese.\n"
            "Maintain the same numbering format in your output.\n"
            "Rules:\n"
            "- Do NOT translate proper nouns, brand names, or technical terms that are commonly kept in English (e.g., CLI, API, PDF, Python, Git).\n"
            "- Do NOT add any explanations, notes, or conversational text.\n"
            "- Keep the translation concise — the translated text should be similar in length to the original when possible.\n"
            "- If a input block is prefixed with '(Table Cell)', it belongs to a narrow table column. You MUST translate it extremely concisely (using shorter words or abbreviations if common) to prevent layout overflow. Do not include the '(Table Cell)' marker in your translation.\n"
            "- If a block has a (Role: ...) or (Context: ...) prefix, use that information to guide your translation style and terminology. Do not include these markers in your output.\n"
            "- For headings, keep the translation concise and impactful.\n"
            "- For figure captions, maintain technical accuracy.\n"
            "- For footnotes, use appropriate scholarly Vietnamese.\n"
            "\n"
            "Input format:\n"
            "[1] Text block 1\n"
            "[2] (Table Cell) Text block 2\n"
            "\n"
            "Output format:\n"
            "[1] Bản dịch block 1\n"
            "[2] Bản dịch ngắn của block 2"
        )

    def _build_prompt(self, blocks: list[TextBlock]) -> str:
        """Xây dựng prompt gộp các block kèm theo số thứ tự (1-based) và các marker ngữ cảnh/ô bảng."""
        lines = []
        for i, block in enumerate(blocks, start=1):
            clean_text = re.sub(r"\s+", " ", block.text).strip()
            prefix_parts = []

            if block.is_table_cell:
                prefix_parts.append("(Table Cell)")
            if block.semantic_role:
                role_label = block.semantic_role.replace("_", " ").title()
                prefix_parts.append(f"(Role: {role_label})")
            if block.semantic_context:
                prefix_parts.append(f"(Context: {block.semantic_context})")

            prefix = " ".join(prefix_parts)
            if prefix:
                lines.append(f"[{i}] {prefix} {clean_text}")
            else:
                lines.append(f"[{i}] {clean_text}")
        return "\n".join(lines)

    def _parse_response(
        self, response: str, original_blocks: list[TextBlock]
    ) -> dict[int, str]:
        """Parse response từ LLM thành dictionary map từ index (0-based) sang bản dịch."""
        # Regex tìm [index] ở đầu dòng và nội dung tiếp sau cho tới khi gặp [index tiếp theo] ở đầu dòng hoặc hết chuỗi
        pattern = r"(?:^|\n)\s*\[(\d+)\]\s*(.*?)(?=\s*(?:\n\s*\[\d+\]|$))"
        matches = re.findall(pattern, response, re.DOTALL)

        parsed_map: dict[int, str] = {}
        for num_str, text in matches:
            try:
                idx = int(num_str) - 1
                if 0 <= idx < len(original_blocks):
                    cleaned_text = text.strip()
                    # Loại bỏ các marker nếu LLM vô tình lặp lại ở đầu bản dịch
                    while True:
                        new_text = re.sub(r"^\((?:Table Cell|Role:\s*[^)]+|Context:\s*[^)]+)\)\s*", "", cleaned_text, flags=re.IGNORECASE)
                        if new_text == cleaned_text:
                            break
                        cleaned_text = new_text
                    parsed_map[idx] = cleaned_text
            except ValueError:
                continue

        return parsed_map

    def _build_fallback_blocks(
        self, original_blocks: list[TextBlock], parsed_map: dict[int, str]
    ) -> list[TranslatedBlock]:
        """Tạo danh sách các TranslatedBlock từ map dịch, fallback về text gốc nếu thiếu."""
        result: list[TranslatedBlock] = []
        for i, block in enumerate(original_blocks):
            # Nếu có bản dịch thì lấy bản dịch, nếu không thì fallback về text gốc
            translated_text = parsed_map.get(i, block.text)
            result.append(
                TranslatedBlock(
                    original=block,
                    translated_text=translated_text,
                    adjusted_font_size=block.font_size,
                )
            )
        return result

    async def _call_api(
        self, system_prompt: str, prompt: str, max_retries: int = 3
    ) -> str:
        """Gọi API của LLM với cơ chế retry và exponential backoff."""
        delay = 1.0
        for attempt in range(max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,  # Nhiệt độ thấp giúp sinh kết quả nhất quán
                )
                content = response.choices[0].message.content
                if content:
                    return content
                raise ValueError("API trả về nội dung trống.")
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                logger.warning(
                    f"Lỗi gọi API dịch (lần {attempt + 1}/{max_retries}): {e}. "
                    f"Đang thử lại sau {delay} giây..."
                )
                await asyncio.sleep(delay)
                delay *= 2

        raise RuntimeError("Không thể gọi API sau số lần thử tối đa.")

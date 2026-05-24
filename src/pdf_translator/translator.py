"""Translator — Dịch văn bản sử dụng API tương thích OpenAI (DeepSeek).

Tích hợp API dịch thuật, gộp các block của trang để dịch trong 1 request,
và xử lý rate limits, định dạng trả về, retry/fallback.
"""

from __future__ import annotations

import asyncio
import re
import openai

from pdf_translator.models import AppConfig, TextBlock, TranslatedBlock
from pdf_translator.logger import get_logger

logger = get_logger(__name__)


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

    async def translate_page(
        self, blocks: list[TextBlock]
    ) -> list[TranslatedBlock]:
        """Dịch toàn bộ các text blocks trên một trang.

        Gộp tất cả text blocks thành một prompt duy nhất để tối ưu chi phí
        và giữ ngữ cảnh liền mạch.

        Args:
            blocks: Danh sách TextBlock cần dịch.

        Returns:
            Danh sách các TranslatedBlock đã được dịch.
        """
        if not blocks:
            return []

        prompt = self._build_prompt(blocks)
        system_prompt = self._get_system_prompt()

        async with self.semaphore:
            try:
                response = await self._call_api(system_prompt, prompt)
                parsed_map = self._parse_response(response, blocks)

                # Kiểm tra xem có đủ tất cả các block không
                if all(i in parsed_map for i in range(len(blocks))):
                    return [
                        TranslatedBlock(
                            original=blocks[i],
                            translated_text=parsed_map[i],
                            adjusted_font_size=blocks[i].font_size,
                        )
                        for i in range(len(blocks))
                    ]

                logger.warning(
                    f"Kết quả dịch thiếu block hoặc sai định dạng trên trang {blocks[0].page_number}. "
                    f"Đang thực hiện dịch lại với chỉ dẫn chặt chẽ hơn..."
                )
            except Exception as e:
                logger.warning(
                    f"Lỗi khi gọi API dịch trên trang {blocks[0].page_number}: {e}. "
                    f"Đang thực hiện dịch lại..."
                )

            # Retry 1 lần với strict system prompt
            try:
                strict_system_prompt = (
                    self._get_system_prompt()
                    + "\n\nCRITICAL: You must return exactly the same number of translation blocks as the input. "
                    "Do not omit any numbers. Do not add any explanations or notes. "
                    "Format each output block starting with the correct index bracket: [index] translation text."
                )
                response = await self._call_api(strict_system_prompt, prompt)
                parsed_map = self._parse_response(response, blocks)

                if all(i in parsed_map for i in range(len(blocks))):
                    return [
                        TranslatedBlock(
                            original=blocks[i],
                            translated_text=parsed_map[i],
                            adjusted_font_size=blocks[i].font_size,
                        )
                        for i in range(len(blocks))
                    ]

                logger.error(
                    f"Dịch lại trang {blocks[0].page_number} vẫn thất bại hoặc thiếu block. "
                    f"Sẽ dùng cơ chế fallback giữ nguyên văn bản gốc cho các block thiếu."
                )
                return self._build_fallback_blocks(blocks, parsed_map)
            except Exception as e:
                logger.error(
                    f"Thất bại hoàn toàn khi dịch trang {blocks[0].page_number}: {e}"
                )
                return self._build_fallback_blocks(blocks, {})

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
            "\n"
            "Input format:\n"
            "[1] Text block 1\n"
            "[2] Text block 2\n"
            "\n"
            "Output format:\n"
            "[1] Bản dịch block 1\n"
            "[2] Bản dịch block 2"
        )

    def _build_prompt(self, blocks: list[TextBlock]) -> str:
        """Xây dựng prompt gộp các block kèm theo số thứ tự (1-based)."""
        lines = []
        for i, block in enumerate(blocks, start=1):
            # Thay thế các khoảng trắng xuống dòng dư thừa thành 1 dấu cách để làm sạch câu trước khi gửi
            clean_text = re.sub(r"\s+", " ", block.text).strip()
            lines.append(f"[{i}] {clean_text}")
        return "\n".join(lines)

    def _parse_response(
        self, response: str, original_blocks: list[TextBlock]
    ) -> dict[int, str]:
        """Parse response từ LLM thành dictionary map từ index (0-based) sang bản dịch."""
        # Regex tìm [index] và nội dung tiếp sau cho tới khi gặp [index tiếp theo] hoặc hết chuỗi
        pattern = r"\[(\d+)\]\s*(.*?)(?=\s*(?:\[\d+\]|$))"
        matches = re.findall(pattern, response, re.DOTALL)

        parsed_map: dict[int, str] = {}
        for num_str, text in matches:
            try:
                idx = int(num_str) - 1
                if 0 <= idx < len(original_blocks):
                    parsed_map[idx] = text.strip()
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

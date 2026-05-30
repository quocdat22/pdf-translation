"""Pipeline Orchestrator — quản lý và điều phối luồng xử lý PDF dịch thuật.

Điều phối luồng qua 3 bước:
1. Extract (Đọc PDF gốc, trích xuất text và metadata - tuần tự)
2. Translate (Gửi text đi dịch song song thông qua DeepSeek API)
3. Render & Save (Xóa text cũ, vẽ text dịch mới, và tối ưu hóa file PDF đầu ra - tuần tự)
"""

from __future__ import annotations

import asyncio
import fitz  # PyMuPDF
from tqdm import tqdm

from pdf_translator.models import AppConfig, TranslatedBlock, TranslationResult, TextBlock
from pdf_translator.extractor import TextExtractor
from pdf_translator.translator import Translator
from pdf_translator.font_manager import FontManager
from pdf_translator.renderer import TextRenderer
from pdf_translator.logger import get_logger

logger = get_logger(__name__)


class PDFProcessor:
    """Điều phối toàn bộ quy trình: Extract -> Translate -> Render -> Save."""

    def __init__(self, config: AppConfig) -> None:
        """Khởi tạo PDFProcessor.

        Args:
            config: Cấu hình ứng dụng AppConfig.
        """
        self.config = config
        self.extractor = TextExtractor()
        self.translator = Translator(config)
        self.font_manager = FontManager(config.font_path or None)
        self.renderer = TextRenderer(self.font_manager)

    async def process(
        self,
        input_path: str,
        output_path: str,
        pages: list[int] | None = None,
        dry_run: bool = False,
    ) -> None:
        """Quy trình chính xử lý và dịch tài liệu PDF.

        Args:
            input_path: Đường dẫn file PDF đầu vào.
            output_path: Đường dẫn file PDF đầu ra.
            pages: Danh sách số trang cần dịch (0-indexed). Nếu None, dịch toàn bộ tài liệu.
            dry_run: Nếu True, chỉ chạy trích xuất văn bản để xem trước cấu trúc, không dịch hay lưu.
        """
        doc = fitz.open(input_path)
        try:
            total_pages = len(doc)
            target_pages = pages if pages is not None else list(range(total_pages))

            # Đảm bảo các trang nằm trong phạm vi chỉ mục hợp lệ
            target_pages = [p for p in target_pages if 0 <= p < total_pages]
            if not target_pages:
                logger.warning("Không có trang hợp lệ nào cần được dịch.")
                return

            if dry_run:
                self._dry_run(doc, target_pages)
                return

            logger.info(f"Bắt đầu dịch PDF: {input_path} ({len(target_pages)} trang)")

            # --- Phase 1: Extract (sequential, sync) ---
            phase_prefix = "1/4" if self.config.vision_enabled else "1/3"
            logger.info(f"Phase {phase_prefix}: Trích xuất văn bản gốc từ PDF...")
            page_blocks: dict[int, list[TextBlock]] = {}
            for page_num in target_pages:
                page = doc[page_num]
                blocks = self.extractor.extract_page(page)
                page_blocks[page_num] = blocks
                logger.debug(f"Trang {page_num}: Đã trích xuất {len(blocks)} blocks.")

            # --- Phase 1.5: Vision Analysis (sequential, sync) ---
            if self.config.vision_enabled:
                logger.info("Phase 2/4: Phân tích layout bằng Vision AI...")
                from pdf_translator.vision_analyzer import VisionAnalyzer
                vision = VisionAnalyzer(self.config)  # Raises nếu Ollama fail

                for page_num in tqdm(target_pages, desc="Vision analysis", unit="trang"):
                    blocks = page_blocks.get(page_num, [])
                    if not blocks:
                        continue
                    page = doc[page_num]
                    regions = vision.analyze_page(page, page_num)
                    page_blocks[page_num] = vision.enrich_blocks(
                        blocks, regions, page.rect
                    )
                    logger.debug(
                        f"Trang {page_num}: Phân tích {len(regions)} regions, "
                        f"enriched {sum(1 for b in page_blocks[page_num] if b.semantic_role)} blocks."
                    )

            # --- Phase 2: Translate (async parallel) ---
            phase_prefix = "3/4" if self.config.vision_enabled else "2/3"
            logger.info(f"Phase {phase_prefix}: Đang thực hiện dịch thuật song song...")
            tasks = []
            for page_num in target_pages:
                blocks = page_blocks[page_num]
                if blocks:
                    task = self._translate_page_wrapper(page_num, blocks)
                    tasks.append(task)
                else:
                    logger.debug(f"Trang {page_num}: Trống hoặc không có văn bản cần dịch.")

            translated_results: dict[int, TranslationResult] = {}
            if tasks:
                with tqdm(total=len(tasks), desc="Dịch trang", unit="trang") as pbar:
                    for coro in asyncio.as_completed(tasks):
                        page_num, translated, success, error_msg = await coro
                        translated_results[page_num] = TranslationResult(
                            page_number=page_num,
                            blocks=translated,
                            success=success,
                            error=error_msg,
                        )
                        pbar.update(1)
            else:
                logger.info("Tài liệu không có văn bản nào cần gửi đi dịch.")

            # --- Phase 3: Render (sequential, sync) ---
            phase_prefix = "4/4" if self.config.vision_enabled else "3/3"
            logger.info(f"Phase {phase_prefix}: Render văn bản dịch lên PDF...")
            for page_num in target_pages:
                blocks = page_blocks[page_num]
                if not blocks:
                    continue

                res = translated_results.get(page_num)
                if not res or not res.success:
                    logger.warning(
                        f"Bỏ qua render Trang {page_num} do dịch thất bại: {res.error if res else 'Unknown error'}"
                    )
                    continue

                page = doc[page_num]
                try:
                    self.renderer.render_page(
                        page=page,
                        translated_blocks=res.blocks,
                        min_font_size=self.config.min_font_size,
                    )
                    logger.debug(f"Trang {page_num}: Render thành công.")
                except Exception as e:
                    logger.error(f"Lỗi khi render Trang {page_num}: {e}")

            if self.config.bilingual:
                logger.info("Tạo tài liệu song ngữ (bilingual side-by-side)...")
                doc_bilingual = fitz.open()
                doc_orig = fitz.open(input_path)
                try:
                    for page_num in range(total_pages):
                        page_orig = doc_orig[page_num]
                        is_translated = page_num in target_pages and (
                            page_num not in translated_results
                            or translated_results[page_num].success
                        )
                        if is_translated:
                            w = page_orig.rect.width
                            h = page_orig.rect.height
                            
                            new_page = doc_bilingual.new_page(width=w * 2, height=h)
                            
                            # Place original page on the left
                            left_rect = fitz.Rect(0, 0, w, h)
                            new_page.show_pdf_page(left_rect, doc_orig, page_num)
                            
                            # Place translated page on the right
                            right_rect = fitz.Rect(w, 0, w * 2, h)
                            new_page.show_pdf_page(right_rect, doc, page_num)
                            
                            # Draw a thin grey separator line in the middle
                            new_page.draw_line(
                                fitz.Point(w, 0),
                                fitz.Point(w, h),
                                color=(0.7, 0.7, 0.7),
                                width=0.5
                            )
                        else:
                            # Not translated or failed -> single width original page
                            w = page_orig.rect.width
                            h = page_orig.rect.height
                            new_page = doc_bilingual.new_page(width=w, height=h)
                            new_page.show_pdf_page(new_page.rect, doc_orig, page_num)
                    
                    logger.info(f"Lưu file PDF song ngữ tại: {output_path}")
                    doc_bilingual.save(output_path, garbage=3, deflate=True)
                finally:
                    doc_bilingual.close()
                    doc_orig.close()
            else:
                # Lưu tài liệu đã dịch bằng cách dọn dẹp các đối tượng thừa và nén PDF
                logger.info(f"Lưu file PDF dịch thuật tại: {output_path}")
                doc.save(output_path, garbage=3, deflate=True)
            logger.info("Dịch thuật hoàn tất.")

        finally:
            doc.close()

    async def _translate_page_wrapper(
        self, page_num: int, blocks: list[TextBlock]
    ) -> tuple[int, list[TranslatedBlock], bool, str | None]:
        """Bọc coroutine dịch trang để thu thập thông tin chỉ mục và xử lý lỗi."""
        try:
            translated = await self.translator.translate_page(blocks)
            return page_num, translated, True, None
        except Exception as e:
            logger.exception(f"Lỗi khi dịch trang {page_num}: {e}")
            return page_num, [], False, str(e)

    def _dry_run(self, doc: fitz.Document, target_pages: list[int]) -> None:
        """Chạy thử (dry-run) để kiểm tra các văn bản trích xuất mà không dịch."""
        logger.info("=== BẮT ĐẦU DRY-RUN (CHỈ XEM TEXT TRÍCH XUẤT) ===")
        total_blocks = 0
        for page_num in target_pages:
            page = doc[page_num]
            blocks = self.extractor.extract_page(page)
            total_blocks += len(blocks)
            logger.info(
                f"Trang {page_num}: Tìm thấy {len(blocks)} text block."
            )
            for block in blocks:
                truncated_text = (
                    block.text[:100] + "..." if len(block.text) > 100 else block.text
                )
                logger.info(
                    f"  ├─ Block {block.block_id:02d} | size={block.font_size:.1f} | bbox=({block.bbox[0]:.1f}, {block.bbox[1]:.1f}, {block.bbox[2]:.1f}, {block.bbox[3]:.1f}) | font={block.font_name}"
                )
                logger.info(f"  │  Text: \"{truncated_text}\"")
        logger.info(
            f"=== KẾT THÚC DRY-RUN | Tổng số: {len(target_pages)} trang, {total_blocks} blocks ==="
        )

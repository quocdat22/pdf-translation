"""Vision Analyzer — Phân tích bố cục trang PDF sử dụng mô hình Vision của Ollama.

Tải ảnh trang PDF, gửi lên Ollama vision model để nhận diện các vùng ngữ nghĩa,
sau đó mapping ngược lại các TextBlock dựa trên độ chồng lấp (IoU) bounding box.
"""

from __future__ import annotations

import base64
import json
import urllib.request
import urllib.error
import fitz  # PyMuPDF

from pdf_translator.models import AppConfig, TextBlock, SemanticRegion
from pdf_translator.logger import get_logger

logger = get_logger(__name__)


class VisionAnalyzer:
    """Phân tích layout trang PDF bằng Ollama vision model."""

    def __init__(self, config: AppConfig) -> None:
        """Khởi tạo VisionAnalyzer.

        Args:
            config: Cấu hình ứng dụng chứa vision settings.

        Raises:
            ConnectionError: Nếu Ollama không khả dụng.
            RuntimeError: Nếu vision model chưa được tải trên Ollama.
        """
        self.config = config
        self.check_ollama_availability()

    def check_ollama_availability(self) -> None:
        """Kiểm tra Ollama server và model có sẵn sàng không.

        Gọi GET /api/tags để kiểm tra server.
        Kiểm tra model name có trong danh sách models.
        Raises ConnectionError hoặc RuntimeError nếu có vấn đề.
        """
        base_url = self.config.vision_ollama_base_url.rstrip("/")
        tags_url = f"{base_url}/api/tags"
        
        try:
            req = urllib.request.Request(tags_url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Không thể kết nối Ollama tại {self.config.vision_ollama_base_url}\n"
                f"Hướng dẫn:\n"
                f"1. Cài đặt Ollama: https://ollama.ai/download\n"
                f"2. Khởi động: ollama serve\n"
                f"3. Tải model: ollama pull {self.config.vision_ollama_model}"
            ) from e
        except Exception as e:
            raise ConnectionError(
                f"Không thể kết nối Ollama tại {self.config.vision_ollama_base_url}: {e}"
            ) from e

        models = data.get("models", [])
        model_names = [m.get("name", "") for m in models]
        
        target_model = self.config.vision_ollama_model
        # So sánh tên model (chính xác hoặc chấp nhận hậu tố như :latest)
        has_model = False
        for name in model_names:
            if (
                name == target_model
                or name.startswith(target_model + ":")
                or (":" not in target_model and name.split(":")[0] == target_model)
            ):
                has_model = True
                break

        if not has_model:
            raise RuntimeError(
                f"Model '{target_model}' chưa được tải trên Ollama server.\n"
                f"Hướng dẫn:\n"
                f"1. Tải model bằng lệnh: ollama pull {target_model}"
            )

    def analyze_page(
        self, page: fitz.Page, page_number: int
    ) -> list[SemanticRegion]:
        """Phân tích layout của 1 trang PDF.

        Args:
            page: Trang PDF từ PyMuPDF.
            page_number: Số trang (cho logging).

        Returns:
            Danh sách SemanticRegion mô tả layout trang.

        Raises:
            RuntimeError: Nếu Ollama trả về kết quả không parse được.
        """
        try:
            img_bytes = self._render_page_to_image(page)
            resp_text = self._call_ollama_vision(img_bytes)
            return self._parse_vision_response(resp_text)
        except Exception as e:
            logger.error(f"Lỗi phân tích layout trang {page_number}: {e}")
            raise RuntimeError(f"Phân tích trang {page_number} thất bại: {e}") from e

    def enrich_blocks(
        self,
        blocks: list[TextBlock],
        regions: list[SemanticRegion],
        page_rect: fitz.Rect,
    ) -> list[TextBlock]:
        """Gán semantic info từ regions vào TextBlocks dựa trên IoU overlap.

        Args:
            blocks: TextBlocks đã extract từ PyMuPDF.
            regions: SemanticRegions từ vision analysis.
            page_rect: Kích thước trang để convert bbox normalized → absolute.

        Returns:
            TextBlocks đã được enriched (semantic_role, semantic_context, region_id).
        """
        width = page_rect.x1 - page_rect.x0
        height = page_rect.y1 - page_rect.y0

        for block in blocks:
            best_iou = 0.0
            best_region = None

            for region in regions:
                # Convert normalized bbox (0.0 - 1.0) to absolute PDF coordinates (pt)
                abs_bbox = (
                    page_rect.x0 + region.bbox[0] * width,
                    page_rect.y0 + region.bbox[1] * height,
                    page_rect.x0 + region.bbox[2] * width,
                    page_rect.y0 + region.bbox[3] * height,
                )

                iou = self._calculate_iou(block.bbox, abs_bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_region = region

            if best_iou >= 0.3 and best_region is not None:
                block.semantic_role = best_region.role
                block.semantic_context = best_region.context
                block.region_id = best_region.region_id

        return blocks

    def _render_page_to_image(self, page: fitz.Page) -> bytes:
        """Render trang PDF thành PNG bytes."""
        pix = page.get_pixmap(dpi=self.config.vision_dpi)
        return pix.tobytes("png")

    def _call_ollama_vision(self, image_bytes: bytes) -> str:
        """Gọi Ollama API với ảnh, trả về raw response text."""
        base_url = self.config.vision_ollama_base_url.rstrip("/")
        chat_url = f"{base_url}/api/chat"

        prompt = (
            "Analyze the layout of this document page. Identify all distinct content regions.\n\n"
            "For each region, provide:\n"
            '- "bbox": [x0, y0, x1, y1] as ratios (0.0 to 1.0) of page width/height\n'
            '- "role": one of: paragraph, heading, subheading, figure_caption, table_header, table_cell, footnote, list_item, page_header, page_footer, sidebar, abstract, reference, equation\n'
            '- "context": brief description of what this region contains\n'
            '- "related_to": list of region IDs this region relates to (e.g., caption relates to its figure)\n\n'
            "Return JSON: {\"regions\": [...]}"
        )

        img_b64 = base64.b64encode(image_bytes).decode("utf-8")
        payload = {
            "model": self.config.vision_ollama_model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [img_b64],
                }
            ],
            "stream": False,
            "format": "json",
            "think": False,
        }

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            chat_url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        # Dùng cấu hình vision_timeout cho local Ollama vision model sinh kết quả
        with urllib.request.urlopen(req, timeout=self.config.vision_timeout) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            return resp_data["message"]["content"]

    def _parse_vision_response(self, response: str) -> list[SemanticRegion]:
        """Parse JSON response từ Ollama thành list[SemanticRegion], hỗ trợ tự động sửa lỗi định dạng."""
        cleaned_response = response.strip()
        # Loại bỏ markdown code blocks nếu có
        if cleaned_response.startswith("```"):
            lines = cleaned_response.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned_response = "\n".join(lines).strip()

        try:
            data = json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Ollama trả về kết quả không parse được JSON: {response}"
            ) from e

        # Xác định danh sách các region
        regions_list = None
        if isinstance(data, list):
            regions_list = data
        elif isinstance(data, dict):
            if "regions" in data and isinstance(data["regions"], list):
                regions_list = data["regions"]
            else:
                # Tìm xem có trường nào chứa danh sách không
                for val in data.values():
                    if isinstance(val, list):
                        regions_list = val
                        break

        if regions_list is None:
            raise RuntimeError(
                f"Ollama JSON format không hợp lệ, thiếu key 'regions': {response}"
            )

        regions = []
        for i, reg_data in enumerate(regions_list):
            if not isinstance(reg_data, dict):
                continue

            region_id = reg_data.get("region_id", reg_data.get("id", i))
            
            # Kiểm tra các loại key bounding box khác nhau
            bbox_list = None
            is_bbox_2d = False
            for key in ("bbox", "bbox_2d", "box"):
                if key in reg_data:
                    bbox_list = reg_data[key]
                    if key == "bbox_2d":
                        is_bbox_2d = True
                    break

            if not bbox_list or len(bbox_list) != 4:
                continue

            try:
                coords = [float(x) for x in bbox_list]
            except (ValueError, TypeError):
                continue

            # Nếu tọa độ được chuẩn hóa thang 1000 (ví dụ [142, 81, 864, 149]), đưa về 0.0 - 1.0
            if any(x > 1.0 for x in coords):
                coords = [x / 1000.0 for x in coords]

            # Đối với bbox_2d (từ Qwen2-VL), thứ tự là [ymin, xmin, ymax, xmax] -> chuyển sang [xmin, ymin, xmax, ymax]
            if is_bbox_2d:
                ymin, xmin, ymax, xmax = coords
                coords = [xmin, ymin, xmax, ymax]

            bbox = (coords[0], coords[1], coords[2], coords[3])
            role = reg_data.get("role", "paragraph")
            context = reg_data.get("context", "")
            
            # Map 'related_to' hoặc 'related_regions'
            related_to = reg_data.get("related_to", reg_data.get("related_regions", []))
            if isinstance(related_to, (int, float)):
                related_regions = [int(related_to)]
            elif isinstance(related_to, list):
                related_regions = [
                    int(x)
                    for x in related_to
                    if isinstance(x, (int, float, str)) and str(x).isdigit()
                ]
            else:
                related_regions = []

            regions.append(
                SemanticRegion(
                    region_id=int(region_id),
                    bbox=bbox,
                    role=role,
                    context=context,
                    related_regions=related_regions,
                )
            )

        return regions

    def _calculate_iou(
        self, bbox1: tuple[float, float, float, float], bbox2: tuple[float, float, float, float]
    ) -> float:
        """Tính Intersection over Union (IoU) giữa 2 bounding box dạng (x0, y0, x1, y1)."""
        x0 = max(bbox1[0], bbox2[0])
        y0 = max(bbox1[1], bbox2[1])
        x1 = min(bbox1[2], bbox2[2])
        y1 = min(bbox1[3], bbox2[3])

        if x1 <= x0 or y1 <= y0:
            return 0.0

        intersection = (x1 - x0) * (y1 - y0)
        area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
        area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
        union = area1 + area2 - intersection

        if union <= 0.0:
            return 0.0
        return intersection / union

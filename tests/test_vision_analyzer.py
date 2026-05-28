"""Unit tests cho vision_analyzer.py."""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
import fitz

from pdf_translator.models import AppConfig, TextBlock, SemanticRegion
from pdf_translator.vision_analyzer import VisionAnalyzer


@pytest.fixture
def base_config() -> AppConfig:
    """Fixture cung cấp AppConfig mặc định phục vụ test."""
    cfg = AppConfig()
    cfg.vision_enabled = True
    cfg.vision_ollama_base_url = "http://localhost:11434"
    cfg.vision_ollama_model = "qwen3.5:2b"
    cfg.vision_dpi = 200
    return cfg


@patch("urllib.request.urlopen")
def test_check_ollama_available(mock_urlopen, base_config):
    """Kiểm tra thành công khi Ollama hoạt động và đã tải model."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"models": [{"name": "qwen3.5:2b"}]}
    ).encode("utf-8")
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    # Khởi tạo không bắn lỗi
    analyzer = VisionAnalyzer(base_config)
    assert analyzer.config.vision_ollama_model == "qwen3.5:2b"


@patch("urllib.request.urlopen")
def test_check_ollama_unavailable(mock_urlopen, base_config):
    """Kiểm tra bắn ConnectionError khi server không hoạt động."""
    mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

    with pytest.raises(ConnectionError) as exc_info:
        VisionAnalyzer(base_config)

    assert "Không thể kết nối Ollama" in str(exc_info.value)
    assert "ollama serve" in str(exc_info.value)


@patch("urllib.request.urlopen")
def test_check_ollama_model_missing(mock_urlopen, base_config):
    """Kiểm tra bắn RuntimeError khi server hoạt động nhưng thiếu model."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"models": [{"name": "llama3:latest"}]}
    ).encode("utf-8")
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    with pytest.raises(RuntimeError) as exc_info:
        VisionAnalyzer(base_config)

    assert "Model 'qwen3.5:2b' chưa được tải" in str(exc_info.value)
    assert "ollama pull" in str(exc_info.value)


class TestVisionAnalyzerLogic:
    @pytest.fixture(autouse=True)
    def setup_analyzer(self, monkeypatch):
        """Mock check_ollama_availability để tránh gọi mạng khi khởi tạo."""
        monkeypatch.setattr(
            VisionAnalyzer, "check_ollama_availability", lambda self: None
        )

    def test_calculate_iou(self, base_config):
        analyzer = VisionAnalyzer(base_config)

        # 1. Trùng khít hoàn toàn -> IoU = 1.0
        bbox1 = (0.0, 0.0, 10.0, 10.0)
        bbox2 = (0.0, 0.0, 10.0, 10.0)
        assert analyzer._calculate_iou(bbox1, bbox2) == pytest.approx(1.0)

        # 2. Không giao nhau -> IoU = 0.0
        bbox3 = (10.0, 10.0, 20.0, 20.0)
        assert analyzer._calculate_iou(bbox1, bbox3) == 0.0

        # 3. Giao nhau một phần
        # bbox1 diện tích = 100
        # bbox4 diện tích = 100
        # giao nhau: (5, 5, 10, 10) diện tích = 25
        # hợp: 100 + 100 - 25 = 175
        # IoU = 25 / 175 = 0.142857
        bbox4 = (5.0, 5.0, 15.0, 15.0)
        assert analyzer._calculate_iou(bbox1, bbox4) == pytest.approx(25 / 175)

    def test_parse_vision_response_valid(self, base_config):
        analyzer = VisionAnalyzer(base_config)
        raw_json = json.dumps(
            {
                "regions": [
                    {
                        "region_id": 1,
                        "bbox": [0.1, 0.1, 0.5, 0.5],
                        "role": "heading",
                        "context": "Main Title",
                        "related_to": [2],
                    },
                    {
                        "id": 2,
                        "bbox": [0.1, 0.5, 0.9, 0.9],
                        "role": "paragraph",
                        "context": "Description paragraph",
                        "related_regions": [],
                    },
                ]
            }
        )

        regions = analyzer._parse_vision_response(raw_json)
        assert len(regions) == 2
        
        assert regions[0].region_id == 1
        assert regions[0].bbox == (0.1, 0.1, 0.5, 0.5)
        assert regions[0].role == "heading"
        assert regions[0].context == "Main Title"
        assert regions[0].related_regions == [2]

        assert regions[1].region_id == 2
        assert regions[1].bbox == (0.1, 0.5, 0.9, 0.9)
        assert regions[1].role == "paragraph"
        assert regions[1].context == "Description paragraph"
        assert regions[1].related_regions == []

    def test_parse_vision_response_markdown_code_fences(self, base_config):
        """Kiểm tra parse response tự động bóc tách markdown block ```json ... ```."""
        analyzer = VisionAnalyzer(base_config)
        raw_json_in_markdown = "```json\n" + json.dumps({
            "regions": [
                {
                    "region_id": 1,
                    "bbox": [0.1, 0.1, 0.5, 0.5],
                    "role": "heading",
                    "context": "Title"
                }
            ]
        }) + "\n```"
        regions = analyzer._parse_vision_response(raw_json_in_markdown)
        assert len(regions) == 1
        assert regions[0].region_id == 1
        assert regions[0].bbox == (0.1, 0.1, 0.5, 0.5)

    def test_parse_vision_response_json_array(self, base_config):
        """Kiểm tra parse response dạng JSON array trực tiếp (không nằm trong key 'regions')."""
        analyzer = VisionAnalyzer(base_config)
        raw_json_array = json.dumps([
            {
                "region_id": 4,
                "bbox": [0.2, 0.2, 0.8, 0.8],
                "role": "paragraph",
                "context": "Context paragraph"
            }
        ])
        regions = analyzer._parse_vision_response(raw_json_array)
        assert len(regions) == 1
        assert regions[0].region_id == 4
        assert regions[0].bbox == (0.2, 0.2, 0.8, 0.8)

    def test_parse_vision_response_bbox_2d_and_normalization(self, base_config):
        """Kiểm tra parse response định dạng bbox_2d (Qwen2-VL) tỉ lệ 1000-normalized và [ymin, xmin, ymax, xmax] -> [xmin, ymin, xmax, ymax]."""
        analyzer = VisionAnalyzer(base_config)
        # Bbox gốc của Qwen2-VL: ymin=142, xmin=81, ymax=864, xmax=149
        raw_qwen_json = json.dumps([
            {
                "bbox_2d": [142, 81, 864, 149],
                "role": "paragraph",
                "context": "Qwen test"
            }
        ])
        regions = analyzer._parse_vision_response(raw_qwen_json)
        assert len(regions) == 1
        # Chuyển đổi chuẩn hóa: ymin=0.142, xmin=0.081, ymax=0.864, xmax=0.149
        # Đảo thứ tự: xmin, ymin, xmax, ymax -> [0.081, 0.142, 0.149, 0.864]
        assert regions[0].bbox == pytest.approx((0.081, 0.142, 0.149, 0.864))
        assert regions[0].role == "paragraph"

    def test_parse_vision_response_invalid_json(self, base_config):
        analyzer = VisionAnalyzer(base_config)
        with pytest.raises(RuntimeError) as exc_info:
            analyzer._parse_vision_response("not a json string")
        assert "không parse được JSON" in str(exc_info.value)

    def test_parse_vision_response_invalid_format(self, base_config):
        analyzer = VisionAnalyzer(base_config)
        with pytest.raises(RuntimeError) as exc_info:
            analyzer._parse_vision_response('{"foo": "bar"}')
        assert "thiếu key 'regions'" in str(exc_info.value)

    def test_enrich_blocks_matching(self, base_config):
        analyzer = VisionAnalyzer(base_config)
        page_rect = fitz.Rect(0, 0, 100, 100)  # Page size 100x100

        # Bounding box coordinates in PDF points
        block1 = TextBlock(
            block_id=0,
            text="Heading Text",
            bbox=(10, 10, 50, 50),  # Matches region 1: normalized (0.1, 0.1, 0.5, 0.5) * 100 -> (10, 10, 50, 50)
            font_size=12.0,
            font_name="Helvetica",
            color=0,
        )
        block2 = TextBlock(
            block_id=1,
            text="Footnote content",
            bbox=(10, 80, 90, 95),  # Matches region 2: normalized (0.1, 0.8, 0.9, 0.95) * 100 -> (10, 80, 90, 95)
            font_size=8.0,
            font_name="Helvetica",
            color=0,
        )

        regions = [
            SemanticRegion(
                region_id=10,
                bbox=(0.1, 0.1, 0.5, 0.5),
                role="heading",
                context="Main page heading",
            ),
            SemanticRegion(
                region_id=11,
                bbox=(0.1, 0.8, 0.9, 0.95),
                role="footnote",
                context="Footnote at the bottom",
            ),
        ]

        enriched = analyzer.enrich_blocks([block1, block2], regions, page_rect)
        assert enriched[0].semantic_role == "heading"
        assert enriched[0].semantic_context == "Main page heading"
        assert enriched[0].region_id == 10

        assert enriched[1].semantic_role == "footnote"
        assert enriched[1].semantic_context == "Footnote at the bottom"
        assert enriched[1].region_id == 11

    def test_enrich_blocks_no_match(self, base_config):
        analyzer = VisionAnalyzer(base_config)
        page_rect = fitz.Rect(0, 0, 100, 100)

        # Block nằm hoàn toàn ngoài vùng region
        block = TextBlock(
            block_id=0,
            text="Far away text",
            bbox=(80, 10, 95, 20),
            font_size=10.0,
            font_name="Helvetica",
            color=0,
        )

        regions = [
            SemanticRegion(
                region_id=1,
                bbox=(0.1, 0.1, 0.5, 0.5),  # (10, 10, 50, 50)
                role="heading",
                context="Header",
            )
        ]

        enriched = analyzer.enrich_blocks([block], regions, page_rect)
        assert enriched[0].semantic_role is None
        assert enriched[0].semantic_context is None
        assert enriched[0].region_id is None

    @patch("urllib.request.urlopen")
    def test_analyze_page(self, mock_urlopen, base_config):
        analyzer = VisionAnalyzer(base_config)

        # Mock page get_pixmap
        mock_pixmap = MagicMock()
        mock_pixmap.tobytes.return_value = b"fake_png_bytes"
        mock_page = MagicMock()
        mock_page.get_pixmap.return_value = mock_pixmap

        # Mock Ollama API response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "regions": [
                                {
                                    "region_id": 1,
                                    "bbox": [0.0, 0.0, 1.0, 0.1],
                                    "role": "page_header",
                                    "context": "Header text",
                                }
                            ]
                        }
                    ),
                }
            }
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        regions = analyzer.analyze_page(mock_page, page_number=0)
        assert len(regions) == 1
        assert regions[0].role == "page_header"
        assert regions[0].region_id == 1
        mock_page.get_pixmap.assert_called_once_with(dpi=200)
        # Check that timeout parameter was correctly passed to urlopen
        assert mock_urlopen.call_args[1]["timeout"] is None


    @patch("urllib.request.urlopen")
    def test_analyze_page_with_custom_timeout(self, mock_urlopen, base_config):
        """Kiểm tra truyền tham số timeout tùy chỉnh vào urlopen."""
        base_config.vision_timeout = 600
        analyzer = VisionAnalyzer(base_config)

        # Mock page get_pixmap
        mock_pixmap = MagicMock()
        mock_pixmap.tobytes.return_value = b"fake_png_bytes"
        mock_page = MagicMock()
        mock_page.get_pixmap.return_value = mock_pixmap

        # Mock Ollama API response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "regions": []
                        }
                    ),
                }
            }
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        analyzer.analyze_page(mock_page, page_number=0)
        # Check that timeout parameter was correctly passed to urlopen as 600
        assert mock_urlopen.call_args[1]["timeout"] == 600

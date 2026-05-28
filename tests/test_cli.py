"""Tests cho cli.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pathlib import Path
from click.testing import CliRunner
import fitz

from pdf_translator.cli import main, parse_pages_string


def test_parse_pages_string_valid() -> None:
    """Kiểm tra parse_pages_string với các định dạng hợp lệ."""
    # Trang đơn lẻ
    assert parse_pages_string("1") == [0]
    assert parse_pages_string("5") == [4]

    # Danh sách các trang lẻ
    assert parse_pages_string("1,3,5") == [0, 2, 4]
    assert parse_pages_string(" 1 , 3, 5 ") == [0, 2, 4]

    # Khoảng trang
    assert parse_pages_string("1-3") == [0, 1, 2]
    assert parse_pages_string("5-5") == [4]

    # Kết hợp nhiều định dạng
    assert parse_pages_string("1,3-5,7") == [0, 2, 3, 4, 6]
    assert parse_pages_string("10,2-4, 5, 8-9") == [1, 2, 3, 4, 7, 8, 9]

    # Trùng lặp
    assert parse_pages_string("1,1,1-3,2") == [0, 1, 2]


def test_parse_pages_string_invalid() -> None:
    """Kiểm tra parse_pages_string ném ValueError với định dạng lỗi."""
    invalid_inputs = [
        "",
        "   ",
        ",",
        "1,",
        ",1",
        "1,,2",
        "0",             # Trang phải > 0
        "-1",
        "1-0",
        "5-3",           # start > end
        "1-2-3",         # Nhiều hơn một dấu gạch ngang
        "1-",            # Khoảng thiếu end
        "-2",            # Khoảng thiếu start
        "a",             # Ký tự không phải số
        "1,b,3",
        "1-a",
        "a-3",
    ]
    for inp in invalid_inputs:
        with pytest.raises(ValueError):
            parse_pages_string(inp)


def test_cli_help() -> None:
    """Kiểm tra hiển thị trợ giúp (--help)."""
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Translate a PDF from English to Vietnamese" in result.output
    assert "--pages" in result.output
    assert "--dry-run" in result.output


def test_cli_version() -> None:
    """Kiểm tra hiển thị phiên bản (--version)."""
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "pdf-translator, version" in result.output


@patch("pdf_translator.cli.load_config")
@patch("pdf_translator.cli.validate_config")
@patch("pdf_translator.processor.PDFProcessor")
def test_cli_dry_run(
    mock_processor_class: MagicMock,
    mock_validate_config: MagicMock,
    mock_load_config: MagicMock,
    tmp_path: Path,
) -> None:
    """Kiểm tra CLI chạy chế độ dry-run."""
    # Tạo PDF thật ngắn làm đầu vào
    doc = fitz.open()
    doc.new_page()
    pdf_path = tmp_path / "input.pdf"
    doc.save(pdf_path)
    doc.close()

    mock_config = MagicMock()
    mock_config.api_key = "test-key"
    mock_config.log_level = "INFO"
    mock_config.log_file = None
    mock_load_config.return_value = mock_config
    mock_validate_config.return_value = []

    mock_processor = mock_processor_class.return_value
    mock_processor.process = AsyncMock()

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            str(pdf_path),
            "--dry-run",
            "--pages", "1,2",
            "--log-level", "DEBUG",
        ],
    )

    assert result.exit_code == 0
    # Đảm bảo validate_config không được gọi khi dry-run
    mock_validate_config.assert_not_called()
    
    # Kiểm tra các tham số truyền cho process
    mock_processor.process.assert_called_once_with(
        input_path=str(pdf_path),
        output_path=str(pdf_path.parent / "input_translated.pdf"),
        pages=[0, 1],
        dry_run=True,
    )


@patch("pdf_translator.cli.load_config")
@patch("pdf_translator.cli.validate_config")
def test_cli_config_validation_error(
    mock_validate_config: MagicMock,
    mock_load_config: MagicMock,
    tmp_path: Path,
) -> None:
    """Kiểm tra CLI dừng lại và trả về lỗi nếu cấu hình không hợp lệ."""
    doc = fitz.open()
    doc.new_page()
    pdf_path = tmp_path / "input.pdf"
    doc.save(pdf_path)
    doc.close()

    mock_config = MagicMock()
    mock_config.api_key = ""
    mock_config.log_level = "INFO"
    mock_config.log_file = None
    mock_load_config.return_value = mock_config
    
    # Mô phỏng lỗi validate
    mock_validate_config.return_value = ["API key chưa được cấu hình."]

    runner = CliRunner()
    result = runner.invoke(main, [str(pdf_path)])

    assert result.exit_code == 1
    assert "❌ Lỗi cấu hình:" in result.output
    assert "API key chưa được cấu hình." in result.output


@patch("pdf_translator.cli.load_config")
@patch("pdf_translator.cli.validate_config")
def test_cli_invalid_pages_format(
    mock_validate_config: MagicMock,
    mock_load_config: MagicMock,
    tmp_path: Path,
) -> None:
    """Kiểm tra CLI báo lỗi nếu tham số --pages sai định dạng."""
    doc = fitz.open()
    doc.new_page()
    pdf_path = tmp_path / "input.pdf"
    doc.save(pdf_path)
    doc.close()

    mock_config = MagicMock()
    mock_config.api_key = "test-key"
    mock_config.log_level = "INFO"
    mock_config.log_file = None
    mock_load_config.return_value = mock_config
    mock_validate_config.return_value = []

    runner = CliRunner()
    result = runner.invoke(main, [str(pdf_path), "--pages", "1-a"])

    assert result.exit_code == 1
    assert "❌ Lỗi tham số --pages:" in result.output
    assert "Số trang phải là số nguyên" in result.output


def test_cli_nonexistent_input_file() -> None:
    """Kiểm tra CLI báo lỗi nếu file đầu vào không tồn tại."""
    runner = CliRunner()
    result = runner.invoke(main, ["nonexistent_file.pdf"])
    assert result.exit_code != 0
    assert "does not exist" in result.output


@patch("pdf_translator.cli.load_config")
@patch("pdf_translator.cli.validate_config")
@patch("pdf_translator.processor.PDFProcessor")
def test_cli_vision_override(
    mock_processor_class: MagicMock,
    mock_validate_config: MagicMock,
    mock_load_config: MagicMock,
    tmp_path: Path,
) -> None:
    """Kiểm tra CLI nhận và chuyển tiếp tham số --vision."""
    doc = fitz.open()
    doc.new_page()
    pdf_path = tmp_path / "input.pdf"
    doc.save(pdf_path)
    doc.close()

    mock_config = MagicMock()
    mock_config.api_key = "test-key"
    mock_config.log_level = "INFO"
    mock_config.log_file = None
    mock_load_config.return_value = mock_config
    mock_validate_config.return_value = []

    mock_processor = mock_processor_class.return_value
    mock_processor.process = AsyncMock()

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            str(pdf_path),
            "--vision",
        ],
    )

    assert result.exit_code == 0
    # Đảm bảo cli_overrides chứa vision_enabled = True
    mock_load_config.assert_called_once_with(
        config_path=None,
        cli_overrides={
            "api_key": None,
            "log_level": "INFO",
            "concurrency": None,
            "use_cache": None,
            "vision_enabled": True,
        },
    )

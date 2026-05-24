"""
CLI interface for pdf_translator.

Provides the `pdf-translator` command with options:
  input_file       Input PDF
  -o/--output      Output PDF (default: <input>_translated.pdf)
  -c/--config      TOML config file
  --api-key        DeepSeek API key
  --dry-run        Extract text only, no translation
  --log-level      Log level (DEBUG/INFO/WARNING/ERROR)
  --concurrency    Max concurrent page translations
  --version        Show version

Stub for Phase 1 -- processor.py and other modules will be added in Phase 2+.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Force UTF-8 output on Windows to handle Vietnamese characters
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from pathlib import Path

import click

from pdf_translator import __version__
from pdf_translator.config import load_config, validate_config
from pdf_translator.logger import setup_logger, get_logger


@click.command()
@click.argument("input_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o", "--output", "output_file",
    type=click.Path(path_type=Path),
    default=None,
    help="Output PDF file path. Default: <input>_translated.pdf",
)
@click.option(
    "-c", "--config", "config_file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to TOML config file.",
)
@click.option(
    "--api-key",
    envvar="PDF_TRANSLATOR_API_KEY",
    default=None,
    help="DeepSeek API key (or set PDF_TRANSLATOR_API_KEY env var).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Extract text only, skip translation API.",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="INFO",
    show_default=True,
    help="Log level.",
)
@click.option(
    "--concurrency",
    type=click.IntRange(min=1),
    default=None,
    help="Max number of pages to translate concurrently.",
)
@click.version_option(version=__version__, prog_name="pdf-translator")
def main(
    input_file: Path,
    output_file: Path | None,
    config_file: Path | None,
    api_key: str | None,
    dry_run: bool,
    log_level: str,
    concurrency: int | None,
) -> None:
    """Translate a PDF from English to Vietnamese, preserving the original layout.

    \b
    Examples:
        pdf-translator document.pdf
        pdf-translator document.pdf -o translated.pdf
        pdf-translator document.pdf --dry-run
        pdf-translator document.pdf --concurrency 10 --log-level DEBUG
    """
    # 1. Xác định output path
    if output_file is None:
        output_file = input_file.parent / f"{input_file.stem}_translated.pdf"

    # 2. Load config
    cli_overrides = {
        "api_key": api_key,
        "log_level": log_level,
        "concurrency": concurrency,
    }
    config = load_config(config_path=config_file, cli_overrides=cli_overrides)

    # 3. Setup logger (trước khi dùng logger ở bất kỳ đâu)
    setup_logger(level=config.log_level, log_file=config.log_file)
    logger = get_logger(__name__)

    logger.info(f"pdf-translator v{__version__}")
    logger.info(f"Input:  {input_file}")
    logger.info(f"Output: {output_file}")

    # 4. Validate config (chỉ cần API key khi không phải dry-run)
    if not dry_run:
        errors = validate_config(config)
        if errors:
            click.echo("❌ Lỗi cấu hình:", err=True)
            for err in errors:
                click.echo(f"   • {err}", err=True)
            sys.exit(1)

    # 5. Chạy pipeline (import muộn để tránh circular imports khi Phase 2 chưa có)
    try:
        from pdf_translator.processor import PDFProcessor  # noqa: PLC0415
        processor = PDFProcessor(config)
        asyncio.run(
            processor.process(
                input_path=str(input_file),
                output_path=str(output_file),
                dry_run=dry_run,
            )
        )
        click.echo(f"✅ Hoàn thành: {output_file}")
    except ImportError:
        # Phase 1: processor chưa implement — chỉ báo thông tin
        logger.warning("processor.py chưa được implement (Phase 2+).")
        if dry_run:
            click.echo("ℹ️  Dry-run mode: processor chưa sẵn sàng.")
        else:
            click.echo(
                "⚠️  Pipeline chưa sẵn sàng. Đây là Phase 1 (Foundation).",
                err=True,
            )
    except Exception as e:
        logger.exception(f"Lỗi xử lý: {e}")
        click.echo(f"❌ Lỗi: {e}", err=True)
        sys.exit(1)

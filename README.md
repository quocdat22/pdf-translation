# pdf-translator

CLI tool dịch thuật PDF từ tiếng Anh sang tiếng Việt, bảo toàn bố cục gốc.

## Tính năng

-  Dịch PDF text-based (có text layer) từ Anh → Việt
-  Bảo toàn vị trí, màu sắc, hình ảnh, header/footer
-  Tự động co giãn font size khi văn bản dịch dài hơn bản gốc
-  Dịch song song nhiều trang với asyncio
-  Config file TOML, structured logging, progress bar

## Cài đặt

```bash
# Yêu cầu: Python 3.11+, uv
uv sync
```

## Sử dụng

```bash
# Dịch cơ bản (output: document_translated.pdf)
uv run pdf-translator document.pdf

# Chỉ định file output
uv run pdf-translator document.pdf -o result.pdf

# Chỉ dịch một số trang cụ thể (1-indexed)
uv run pdf-translator document.pdf --pages 1,3,5-8
# Hoặc viết tắt bằng -p
uv run pdf-translator document.pdf -p 2,4-6

# Dry run — chỉ xem text được extract, không gọi API
uv run pdf-translator document.pdf --dry-run

# Dùng config file
uv run pdf-translator document.pdf -c config.toml

# API key qua environment variable (Linux/macOS)
export PDF_TRANSLATOR_API_KEY="sk-xxx"
uv run pdf-translator document.pdf

# Hoặc trên Windows (PowerShell)
$env:PDF_TRANSLATOR_API_KEY="sk-xxx"
uv run pdf-translator document.pdf
```

## Cấu hình

Sao chép file config mẫu thành `config.toml` ở thư mục gốc của dự án và điền API key:

```bash
cp config.example.toml config.toml
# Chỉnh sửa file config.toml vừa tạo với API key DeepSeek của bạn
```

## License

AGPL-3.0-or-later (do phụ thuộc PyMuPDF)

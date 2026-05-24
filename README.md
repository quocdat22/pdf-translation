# pdf-translator

CLI tool dịch thuật PDF từ tiếng Anh sang tiếng Việt, bảo toàn bố cục gốc.

## Tính năng

- ✅ Dịch PDF text-based (có text layer) từ Anh → Việt
- ✅ Bảo toàn vị trí, màu sắc, hình ảnh, header/footer
- ✅ Tự động co giãn font size khi văn bản dịch dài hơn bản gốc
- ✅ Dịch song song nhiều trang với asyncio
- ✅ Config file TOML, structured logging, progress bar

## Cài đặt

```bash
# Yêu cầu: Python 3.11+, uv
uv sync
```

## Sử dụng

```bash
# Dịch cơ bản (output: document_translated.pdf)
pdf-translator document.pdf

# Chỉ định file output
pdf-translator document.pdf -o result.pdf

# Dry run — chỉ xem text được extract, không gọi API
pdf-translator document.pdf --dry-run

# Dùng config file
pdf-translator document.pdf -c my_config.toml

# API key qua environment variable
export PDF_TRANSLATOR_API_KEY="sk-xxx"
pdf-translator document.pdf
```

## Cấu hình

Copy file config mẫu và điền API key:

```bash
cp config.example.toml ~/.config/pdf-translator/config.toml
# Chỉnh sửa file với API key DeepSeek của bạn
```

## License

AGPL-3.0-or-later (do phụ thuộc PyMuPDF)

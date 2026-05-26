# 📄 pdf-translator

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-AGPL--3.0-orange.svg)](https://opensource.org/licenses/AGPL-3.0)
[![Built with uv](https://img.shields.io/badge/built%20with-uv-5b21b6.svg)](https://github.com/astral-sh/uv)

**pdf-translator** là một công cụ dòng lệnh (CLI) mạnh mẽ được thiết kế để dịch thuật tài liệu PDF từ **tiếng Anh sang tiếng Việt** mà vẫn **giữ nguyên bố cục gốc** (layout-preserving). Công cụ sử dụng sức mạng của các mô hình ngôn ngữ lớn (LLM) thông qua API tương thích OpenAI để dịch văn bản một cách tự nhiên và chính xác nhất.

---

## ✨ Tính năng nổi bật

- **🛡️ Bảo toàn bố cục hoàn hảo:** Giữ nguyên vị trí (bounding boxes), màu sắc chữ, các định dạng cơ bản (chữ đậm, chữ nghiêng) và các thành phần đồ họa khác trong file PDF.
- **🔄 Tự động tối ưu kích thước chữ (Auto-Shrink):** Tự động điều chỉnh thu nhỏ cỡ chữ (font size) khi văn bản tiếng Việt dịch ra dài hơn văn bản gốc, tránh việc tràn văn bản hoặc ghi đè lên các phần tử khác.
- **⚡ Dịch song song tốc độ cao:** Tận dụng tối đa lập trình không đồng bộ (`asyncio`) để dịch đồng thời nhiều trang PDF, giúp rút ngắn thời gian xử lý các tài liệu lớn.
- **🌐 Tương thích đa nền tảng LLM:** Hỗ trợ linh hoạt các nhà cung cấp API bao gồm **DeepSeek (Mặc định)**, **OpenAI (GPT-4o)**, **Google Gemini**, hoặc thậm chí các mô hình chạy cục bộ offline qua **Ollama**.
- **🛠️ Cấu hình linh hoạt:** Cho phép thiết lập thông qua file cấu hình TOML, biến môi trường (Environment Variables) hoặc trực tiếp qua đối số dòng lệnh (CLI).
- **📊 Công cụ CLI hiện đại:** Tích hợp thanh tiến trình sinh động (`tqdm`), logging có cấu trúc để gỡ lỗi và chế độ chạy thử nghiệm (`--dry-run`).

---

## ⚙️ Quy trình xử lý (Workflow)

```mermaid
graph TD
    A[PDF Đầu Vào] --> B[Trích xuất - Extractor]
    B -->|Trích xuất Text & Tọa độ bbox & Font/Color| C[Dịch thuật - Translator]
    C -->|Gửi API LLM dịch thuật song song| D[Bộ dựng - Renderer]
    D -->|Vẽ lại Text đã dịch & Tự động scale font| E[PDF Đầu Ra]
```

---

## 🚀 Hướng dẫn cài đặt

Dự án sử dụng **[uv](https://github.com/astral-sh/uv)** - một trình quản lý gói Python cực kỳ nhanh chóng.

### Yêu cầu hệ thống:
- **Python 3.11** trở lên.
- **uv** đã được cài đặt trên hệ thống của bạn.

### Các bước cài đặt:

1. Clone dự án về máy:
   ```bash
   git clone https://github.com/quocdat22/pdf-translation.git
   cd pdf-translation
   ```

2. Đồng bộ hóa môi trường ảo và cài đặt tất cả các phụ thuộc:
   ```bash
   uv sync
   ```

---

## 📝 Cấu hình hệ thống

Ứng dụng nạp cấu hình theo thứ tự ưu tiên từ cao xuống thấp:
1. **CLI arguments** (Tham số dòng lệnh)
2. **Environment variables** (Biến môi trường)
3. **File config TOML** (`config.toml` tại thư mục gốc)
4. **Giá trị mặc định** (Xem thêm tại [models.py](file:///src/pdf_translator/models.py))

### 1. Sử dụng file cấu hình TOML (`config.toml`)
Sao chép file cấu hình mẫu và chỉnh sửa thông tin API Key của bạn:

```bash
cp config.example.toml config.toml
```

Chỉnh sửa file `config.toml` mới tạo:
```toml
[api]
key = "sk-your-deepseek-api-key"
base_url = "https://api.deepseek.com"
model = "deepseek-chat"

[translation]
source_lang = "English"
target_lang = "Vietnamese"
concurrency = 5  # Số trang xử lý song song

[rendering]
min_font_size = 6.0  # Cỡ chữ tối thiểu khi co giãn
```

### 2. Sử dụng biến môi trường (Environment Variables)
Nếu không dùng file cấu hình, bạn có thể thiết lập trực tiếp qua môi trường:

**Trên Linux / macOS:**
```bash
export PDF_TRANSLATOR_API_KEY="sk-xxx"
export PDF_TRANSLATOR_MODEL="deepseek-chat"
```

**Trên Windows (PowerShell):**
```powershell
$env:PDF_TRANSLATOR_API_KEY="sk-xxx"
$env:PDF_TRANSLATOR_MODEL="deepseek-chat"
```

---

## 💻 Hướng dẫn sử dụng

Dưới đây là một số lệnh phổ biến để chạy công cụ:

```bash
# 1. Dịch cơ bản (Kết quả lưu tại: document_translated.pdf)
uv run pdf-translator document.pdf

# 2. Dịch và lưu ra file kết quả cụ thể
uv run pdf-translator document.pdf -o path/to/result.pdf

# 3. Chỉ dịch một số trang cụ thể (Hỗ trợ trang lẻ hoặc khoảng trang)
uv run pdf-translator document.pdf --pages 1,3,5-8

# 4. Chạy chế độ dùng thử (Dry-run) - Chỉ trích xuất văn bản để kiểm tra, không gọi API dịch
uv run pdf-translator document.pdf --dry-run

# 5. Sử dụng một file cấu hình TOML cụ thể
uv run pdf-translator document.pdf -c custom_config.toml

# 6. Điều chỉnh cấp độ ghi log (DEBUG, INFO, WARNING, ERROR)
uv run pdf-translator document.pdf --log-level DEBUG

# 7. Thay đổi số lượng trang xử lý song song trực tiếp từ CLI
uv run pdf-translator document.pdf --concurrency 10
```

### Chi tiết các tham số CLI:

| Tham số | Phím tắt | Kiểu dữ liệu | Mặc định | Mô tả |
| :--- | :--- | :--- | :--- | :--- |
| `input_file` | — | Đường dẫn | (Bắt buộc) | Đường dẫn file PDF đầu vào cần dịch. |
| `--output` | `-o` | Đường dẫn | `<input>_translated.pdf` | Đường dẫn lưu file PDF đầu ra sau khi dịch. |
| `--config` | `-c` | Đường dẫn | `config.toml` | Đường dẫn tới file cấu hình TOML tùy chỉnh. |
| `--api-key` | — | Chuỗi | `None` | API key dịch thuật (Ghi đè cấu hình trong file và Env Var). |
| `--dry-run` | — | Cờ | `False` | Chỉ trích xuất text, không thực hiện dịch thuật và sinh file. |
| `--log-level`| — | Lựa chọn | `INFO` | Cấp độ ghi log: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `--concurrency`|— | Số nguyên | `5` (hoặc TOML) | Số luồng dịch trang song song tối đa. |
| `--pages` | `-p` | Chuỗi | `None` | Chỉ dịch các trang được chọn (ví dụ: `1,3,5-8`). Mặc định dịch toàn bộ. |

---

## 📂 Cấu trúc mã nguồn

```text
pdf-translation/
├── src/
│   └── pdf_translator/
│       ├── cli.py             # Điểm khởi chạy CLI và cấu hình CLI
│       ├── config.py          # Xử lý, nạp và xác thực cấu hình (TOML/Env/CLI)
│       ├── models.py          # Định nghĩa cấu trúc dữ liệu trung tâm (TextBlock, AppConfig...)
│       ├── extractor.py       # Trích xuất văn bản, hình ảnh, tọa độ từ PDF
│       ├── translator.py      # Gửi dữ liệu tới LLM API để dịch (Asyncio)
│       ├── renderer.py        # Vẽ lại văn bản đã dịch lên canvas PDF mới
│       ├── processor.py       # Điều phối toàn bộ vòng đời dịch thuật PDF
│       ├── font_manager.py    # Quản lý fonts chữ hệ thống và tự động co giãn font
│       └── logger.py          # Cấu hình logging
├── tests/                     # Hệ thống kiểm thử tự động (Unit tests & Integration tests)
├── assets/                    # Chứa fonts bổ sung hoặc tài nguyên hệ thống
├── config.example.toml        # File cấu hình mẫu
├── pyproject.toml             # Cấu hình dự án & Phụ thuộc của Python
└── README.md                  # Tài liệu hướng dẫn sử dụng
```

---

## 🧪 Hướng dẫn phát triển & Kiểm thử

Nếu bạn muốn đóng góp cho dự án hoặc chạy kiểm thử:

1. Chạy các bài kiểm thử tự động với `pytest`:
   ```bash
   uv run pytest
   ```

2. Chạy kiểm thử kèm báo cáo độ bao phủ mã nguồn (code coverage):
   ```bash
   uv run pytest --cov=src/pdf_translator tests/
   ```

---

## 📄 Bản quyền (License)

Dự án này được phát hành dưới giấy phép **AGPL-3.0-or-later** (phụ thuộc vào thư viện `PyMuPDF`). Vui lòng tham khảo chi tiết giấy phép để biết thêm thông tin về việc phân phối và sử dụng.

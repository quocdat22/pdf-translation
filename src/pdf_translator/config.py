"""
Config loader cho pdf_translator.

Thứ tự ưu tiên (cao → thấp):
1. CLI arguments (truyền qua cli_overrides)
2. Environment variables (tiền tố PDF_TRANSLATOR_)
3. File config TOML (config.toml ở thư mục gốc của dự án hoặc đường dẫn chỉ định)
4. Giá trị mặc định trong AppConfig
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pdf_translator.models import AppConfig

# Đường dẫn config mặc định: file config.toml ở thư mục gốc của dự án
_THIS_DIR = Path(__file__).parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config.toml"

# Tên các environment variables
ENV_MAP: dict[str, str] = {
    "PDF_TRANSLATOR_API_KEY": "api_key",
    "PDF_TRANSLATOR_API_BASE_URL": "api_base_url",
    "PDF_TRANSLATOR_MODEL": "model",
    "PDF_TRANSLATOR_SOURCE_LANG": "source_lang",
    "PDF_TRANSLATOR_TARGET_LANG": "target_lang",
    "PDF_TRANSLATOR_CONCURRENCY": "concurrency",
    "PDF_TRANSLATOR_MIN_FONT_SIZE": "min_font_size",
    "PDF_TRANSLATOR_FONT_PATH": "font_path",
    "PDF_TRANSLATOR_LOG_LEVEL": "log_level",
    "PDF_TRANSLATOR_LOG_FILE": "log_file",
}


def load_config(
    config_path: Path | None = None,
    cli_overrides: dict | None = None,
) -> AppConfig:
    """Nạp config theo thứ tự ưu tiên: CLI > env > file > default.

    Args:
        config_path: Đường dẫn đến file TOML. Nếu None, thử load từ
            DEFAULT_CONFIG_PATH. Nếu file không tồn tại, bỏ qua.
        cli_overrides: Dict các giá trị ghi đè từ CLI (key = tên field
            trong AppConfig, value = giá trị; None hoặc giá trị None
            trong dict sẽ bị bỏ qua).

    Returns:
        AppConfig đã được nạp và merge.
    """
    # Bước 1: Giá trị mặc định
    config_dict: dict = {}

    # Bước 2: Load từ file TOML
    resolved_path = config_path or DEFAULT_CONFIG_PATH
    if resolved_path.exists():
        try:
            with open(resolved_path, "rb") as f:
                toml_data = tomllib.load(f)
            config_dict.update(_flatten_toml(toml_data))
        except Exception as e:
            # Không để lỗi TOML crash app; sẽ được báo cáo qua validate
            import warnings
            warnings.warn(f"Không thể đọc config file '{resolved_path}': {e}")

    # Bước 3: Override từ environment variables
    for env_var, field_name in ENV_MAP.items():
        value = os.environ.get(env_var)
        if value is not None:
            config_dict[field_name] = value

    # Bước 4: Override từ CLI arguments
    if cli_overrides:
        for key, value in cli_overrides.items():
            if value is not None:
                config_dict[key] = value

    # Build AppConfig, ép kiểu cho các field số
    return _build_config(config_dict)


def validate_config(config: AppConfig) -> list[str]:
    """Validate config, trả về danh sách lỗi (nếu có).

    Args:
        config: AppConfig cần validate.

    Returns:
        List[str] chứa thông báo lỗi. Rỗng nếu config hợp lệ.
    """
    errors: list[str] = []

    # API key bắt buộc
    if not config.api_key or not config.api_key.strip():
        errors.append(
            "API key chưa được cấu hình. "
            "Hãy đặt PDF_TRANSLATOR_API_KEY hoặc thêm vào config file."
        )

    # Concurrency phải > 0
    if config.concurrency < 1:
        errors.append(
            f"concurrency phải >= 1, hiện tại: {config.concurrency}"
        )

    # min_font_size phải > 0
    if config.min_font_size <= 0:
        errors.append(
            f"min_font_size phải > 0, hiện tại: {config.min_font_size}"
        )

    # log_level hợp lệ
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if config.log_level.upper() not in valid_levels:
        errors.append(
            f"log_level không hợp lệ: '{config.log_level}'. "
            f"Chọn một trong: {', '.join(sorted(valid_levels))}"
        )

    # font_path nếu có phải tồn tại
    if config.font_path and not Path(config.font_path).exists():
        errors.append(
            f"font_path không tồn tại: '{config.font_path}'"
        )

    # log_file nếu có, thư mục cha phải tồn tại
    if config.log_file:
        log_dir = Path(config.log_file).parent
        if not log_dir.exists():
            errors.append(
                f"Thư mục chứa log_file không tồn tại: '{log_dir}'"
            )

    return errors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _flatten_toml(data: dict) -> dict:
    """Flatten cấu trúc TOML lồng nhau thành dict phẳng cho AppConfig.

    Ánh xạ:
        [api] key         → api_key
        [api] base_url    → api_base_url
        [api] model       → model
        [translation] *   → *
        [rendering] *     → *
        [logging] level   → log_level
        [logging] log_file→ log_file
    """
    flat: dict = {}

    api = data.get("api", {})
    if "key" in api:
        flat["api_key"] = api["key"]
    if "base_url" in api:
        flat["api_base_url"] = api["base_url"]
    if "model" in api:
        flat["model"] = api["model"]

    translation = data.get("translation", {})
    for k in ("source_lang", "target_lang", "concurrency"):
        if k in translation:
            flat[k] = translation[k]

    rendering = data.get("rendering", {})
    for k in ("min_font_size", "font_path"):
        if k in rendering:
            flat[k] = rendering[k]

    logging_cfg = data.get("logging", {})
    if "level" in logging_cfg:
        flat["log_level"] = logging_cfg["level"]
    if "log_file" in logging_cfg:
        flat["log_file"] = logging_cfg["log_file"]

    return flat


def _build_config(config_dict: dict) -> AppConfig:
    """Tạo AppConfig từ dict, ép kiểu đúng cho từng field."""
    defaults = AppConfig()
    kwargs: dict = {}

    str_fields = {"api_key", "api_base_url", "model", "source_lang",
                  "target_lang", "font_path", "log_level"}
    int_fields = {"concurrency"}
    float_fields = {"min_font_size"}
    opt_str_fields = {"log_file"}

    for field_name in str_fields:
        if field_name in config_dict:
            kwargs[field_name] = str(config_dict[field_name])

    for field_name in int_fields:
        if field_name in config_dict:
            try:
                kwargs[field_name] = int(config_dict[field_name])
            except (ValueError, TypeError):
                pass  # Để validate_config báo lỗi

    for field_name in float_fields:
        if field_name in config_dict:
            try:
                kwargs[field_name] = float(config_dict[field_name])
            except (ValueError, TypeError):
                pass

    for field_name in opt_str_fields:
        if field_name in config_dict:
            val = config_dict[field_name]
            kwargs[field_name] = str(val) if val is not None else None

    # Bắt đầu từ default, rồi apply kwargs
    result = AppConfig()
    for k, v in kwargs.items():
        setattr(result, k, v)

    return result

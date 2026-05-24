"""Shared fixtures và config cho pytest."""

from __future__ import annotations

import pytest
from pathlib import Path

# Thư mục fixtures (PDF mẫu)
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Trả về đường dẫn thư mục fixtures."""
    return FIXTURES_DIR


@pytest.fixture
def sample_config_toml(tmp_path: Path) -> Path:
    """Tạo file config TOML tạm thời cho tests."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[api]
key = "test-api-key"
base_url = "https://api.deepseek.com"
model = "deepseek-chat"

[translation]
concurrency = 3

[rendering]
min_font_size = 6.0

[logging]
level = "DEBUG"
""",
        encoding="utf-8",
    )
    return config_file

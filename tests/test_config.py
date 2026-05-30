"""Unit tests cho config.py."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pdf_translator.config import load_config, validate_config, _flatten_toml
from pdf_translator.models import AppConfig


class TestLoadConfig:
    def test_defaults_when_no_file(self, tmp_path: Path):
        """Không có file config → dùng giá trị mặc định."""
        config = load_config(config_path=tmp_path / "nonexistent.toml")
        assert isinstance(config, AppConfig)
        assert config.api_key == ""
        assert config.concurrency == 5

    def test_default_config_path_is_in_project_root(self):
        """Kiểm tra đường dẫn mặc định nằm ở thư mục gốc của dự án."""
        from pdf_translator.config import DEFAULT_CONFIG_PATH
        assert DEFAULT_CONFIG_PATH.name == "config.toml"
        assert (DEFAULT_CONFIG_PATH.parent / "src").is_dir()
        assert (DEFAULT_CONFIG_PATH.parent / "pyproject.toml").is_file()

    def test_load_from_toml_file(self, sample_config_toml: Path):
        """Load từ file TOML."""
        config = load_config(config_path=sample_config_toml)
        assert config.api_key == "test-api-key"
        assert config.concurrency == 3
        assert config.log_level == "DEBUG"

    def test_cli_override_beats_toml(self, sample_config_toml: Path):
        """CLI override ghi đè giá trị từ file."""
        config = load_config(
            config_path=sample_config_toml,
            cli_overrides={"api_key": "cli-key", "concurrency": 10},
        )
        assert config.api_key == "cli-key"
        assert config.concurrency == 10

    def test_env_var_override(self, sample_config_toml: Path, monkeypatch):
        """Env var ghi đè file config, nhưng CLI > env."""
        monkeypatch.setenv("PDF_TRANSLATOR_API_KEY", "env-key")
        config = load_config(config_path=sample_config_toml)
        assert config.api_key == "env-key"

    def test_cli_beats_env(self, sample_config_toml: Path, monkeypatch):
        """CLI override ghi đè env var."""
        monkeypatch.setenv("PDF_TRANSLATOR_API_KEY", "env-key")
        config = load_config(
            config_path=sample_config_toml,
            cli_overrides={"api_key": "cli-key"},
        )
        assert config.api_key == "cli-key"

    def test_none_cli_values_ignored(self, sample_config_toml: Path):
        """None trong cli_overrides bị bỏ qua → giữ giá trị file."""
        config = load_config(
            config_path=sample_config_toml,
            cli_overrides={"api_key": None, "concurrency": None},
        )
        assert config.api_key == "test-api-key"
        assert config.concurrency == 3

    def test_concurrency_type_coercion(self, sample_config_toml: Path):
        """concurrency từ env var (string) được ép kiểu về int."""
        config = load_config(
            config_path=sample_config_toml,
            cli_overrides={"concurrency": "7"},  # string từ env
        )
        assert config.concurrency == 7
        assert isinstance(config.concurrency, int)

    def test_cache_config(self, monkeypatch):
        """use_cache được nạp mặc định và ghi đè qua env/cli."""
        # 1. Mặc định là True
        config = load_config(config_path=Path("nonexistent.toml"))
        assert config.use_cache is True

        # 2. Ghi đè bởi Env var
        monkeypatch.setenv("PDF_TRANSLATOR_USE_CACHE", "False")
        config = load_config(config_path=Path("nonexistent.toml"))
        assert config.use_cache is False

        # 3. Ghi đè bởi CLI override
        config = load_config(
            config_path=Path("nonexistent.toml"),
            cli_overrides={"use_cache": True}
        )
        assert config.use_cache is True

    def test_vision_config_defaults(self):
        """Kiểm tra giá trị mặc định của cấu hình vision."""
        config = load_config(config_path=Path("nonexistent.toml"))
        assert config.vision_enabled is False
        assert config.vision_ollama_base_url == "http://localhost:11434"
        assert config.vision_ollama_model == "qwen3.5:2b"
        assert config.vision_dpi == 200
        assert config.vision_timeout is None

    def test_load_vision_from_toml(self, tmp_path: Path):
        """Nạp các trường cấu hình vision từ file TOML."""
        toml_file = tmp_path / "config.toml"
        toml_content = """
        [vision]
        enabled = true
        ollama_base_url = "http://localhost:9999"
        ollama_model = "custom-vision:latest"
        dpi = 300
        timeout = 450
        """
        toml_file.write_text(toml_content, encoding="utf-8")
        config = load_config(config_path=toml_file)
        assert config.vision_enabled is True
        assert config.vision_ollama_base_url == "http://localhost:9999"
        assert config.vision_ollama_model == "custom-vision:latest"
        assert config.vision_dpi == 300
        assert config.vision_timeout == 450

    def test_vision_cli_override(self, tmp_path: Path):
        """CLI overrides ghi đè các cấu hình vision."""
        toml_file = tmp_path / "config.toml"
        toml_content = """
        [vision]
        enabled = false
        dpi = 200
        """
        toml_file.write_text(toml_content, encoding="utf-8")
        config = load_config(
            config_path=toml_file,
            cli_overrides={"vision_enabled": True, "vision_dpi": 400, "vision_timeout": 600}
        )
        assert config.vision_enabled is True
        assert config.vision_dpi == 400
        assert config.vision_timeout == 600

    def test_bilingual_config_defaults(self):
        """Kiểm tra giá trị mặc định của cấu hình bilingual."""
        config = load_config(config_path=Path("nonexistent.toml"))
        assert config.bilingual is False

    def test_load_bilingual_from_toml(self, tmp_path: Path):
        """Nạp cấu hình bilingual từ file TOML."""
        toml_file = tmp_path / "config.toml"
        toml_content = """
        [translation]
        bilingual = true
        """
        toml_file.write_text(toml_content, encoding="utf-8")
        config = load_config(config_path=toml_file)
        assert config.bilingual is True

    def test_bilingual_cli_override(self, tmp_path: Path):
        """CLI overrides ghi đè cấu hình bilingual."""
        toml_file = tmp_path / "config.toml"
        toml_content = """
        [translation]
        bilingual = false
        """
        toml_file.write_text(toml_content, encoding="utf-8")
        config = load_config(
            config_path=toml_file,
            cli_overrides={"bilingual": True}
        )
        assert config.bilingual is True



class TestValidateConfig:
    def _valid_config(self) -> AppConfig:
        cfg = AppConfig()
        cfg.api_key = "sk-valid"
        return cfg

    def test_valid_config(self):
        errors = validate_config(self._valid_config())
        assert errors == []

    def test_missing_api_key(self):
        cfg = AppConfig()
        cfg.api_key = ""
        errors = validate_config(cfg)
        assert any("API key" in e for e in errors)

    def test_whitespace_api_key(self):
        cfg = AppConfig()
        cfg.api_key = "   "
        errors = validate_config(cfg)
        assert any("API key" in e for e in errors)

    def test_invalid_concurrency(self):
        cfg = self._valid_config()
        cfg.concurrency = 0
        errors = validate_config(cfg)
        assert any("concurrency" in e for e in errors)

    def test_invalid_min_font_size(self):
        cfg = self._valid_config()
        cfg.min_font_size = -1.0
        errors = validate_config(cfg)
        assert any("min_font_size" in e for e in errors)

    def test_invalid_log_level(self):
        cfg = self._valid_config()
        cfg.log_level = "VERBOSE"
        errors = validate_config(cfg)
        assert any("log_level" in e for e in errors)

    def test_nonexistent_font_path(self):
        cfg = self._valid_config()
        cfg.font_path = "/nonexistent/path/font.ttf"
        errors = validate_config(cfg)
        assert any("font_path" in e for e in errors)

    def test_multiple_errors(self):
        cfg = AppConfig()
        cfg.api_key = ""
        cfg.concurrency = 0
        cfg.log_level = "INVALID"
        errors = validate_config(cfg)
        assert len(errors) >= 3

    def test_invalid_vision_dpi_when_disabled(self):
        """vision_dpi không hợp lệ nhưng vision bị tắt -> không lỗi."""
        cfg = self._valid_config()
        cfg.vision_enabled = False
        cfg.vision_dpi = 10
        errors = validate_config(cfg)
        assert errors == []

    def test_invalid_vision_dpi_when_enabled(self):
        """vision_dpi không hợp lệ khi vision được bật -> lỗi."""
        cfg = self._valid_config()
        cfg.vision_enabled = True
        cfg.vision_dpi = 10  # Dưới 72
        errors = validate_config(cfg)
        assert any("vision_dpi" in e for e in errors)

        cfg.vision_dpi = 700  # Trên 600
        errors = validate_config(cfg)
        assert any("vision_dpi" in e for e in errors)

        cfg.vision_dpi = 300  # Hợp lệ
        errors = validate_config(cfg)
        assert errors == []

    def test_invalid_vision_timeout(self):
        """vision_timeout <= 0 -> lỗi."""
        cfg = self._valid_config()
        cfg.vision_enabled = True
        cfg.vision_timeout = 0
        errors = validate_config(cfg)
        assert any("vision_timeout" in e for e in errors)

        cfg.vision_timeout = -10
        errors = validate_config(cfg)
        assert any("vision_timeout" in e for e in errors)

        cfg.vision_timeout = 10  # Hợp lệ
        errors = validate_config(cfg)
        assert errors == []


class TestFlattenToml:
    def test_full_toml(self):
        data = {
            "api": {"key": "sk-x", "base_url": "https://x.com", "model": "m"},
            "translation": {"source_lang": "En", "target_lang": "Vi", "concurrency": 8, "cache": False},
            "rendering": {"min_font_size": 7.0},
            "logging": {"level": "DEBUG", "log_file": "/tmp/x.log"},
        }
        flat = _flatten_toml(data)
        assert flat["api_key"] == "sk-x"
        assert flat["api_base_url"] == "https://x.com"
        assert flat["model"] == "m"
        assert flat["source_lang"] == "En"
        assert flat["concurrency"] == 8
        assert flat["use_cache"] is False
        assert flat["min_font_size"] == 7.0
        assert flat["log_level"] == "DEBUG"
        assert flat["log_file"] == "/tmp/x.log"

    def test_empty_toml(self):
        flat = _flatten_toml({})
        assert flat == {}

    def test_partial_toml(self):
        data = {"api": {"key": "only-key"}}
        flat = _flatten_toml(data)
        assert flat == {"api_key": "only-key"}

    def test_vision_toml_flatten(self):
        data = {
            "vision": {
                "enabled": True,
                "ollama_base_url": "http://ollama:11434",
                "ollama_model": "model-v",
                "dpi": 150,
                "timeout": 120
            }
        }
        flat = _flatten_toml(data)
        assert flat["vision_enabled"] is True
        assert flat["vision_ollama_base_url"] == "http://ollama:11434"
        assert flat["vision_ollama_model"] == "model-v"
        assert flat["vision_dpi"] == 150
        assert flat["vision_timeout"] == 120

    def test_bilingual_toml_flatten(self):
        data = {
            "translation": {
                "bilingual": True
            }
        }
        flat = _flatten_toml(data)
        assert flat["bilingual"] is True


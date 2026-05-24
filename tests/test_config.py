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


class TestFlattenToml:
    def test_full_toml(self):
        data = {
            "api": {"key": "sk-x", "base_url": "https://x.com", "model": "m"},
            "translation": {"source_lang": "En", "target_lang": "Vi", "concurrency": 8},
            "rendering": {"min_font_size": 7.0},
            "logging": {"level": "DEBUG", "log_file": "/tmp/x.log"},
        }
        flat = _flatten_toml(data)
        assert flat["api_key"] == "sk-x"
        assert flat["api_base_url"] == "https://x.com"
        assert flat["model"] == "m"
        assert flat["source_lang"] == "En"
        assert flat["concurrency"] == 8
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

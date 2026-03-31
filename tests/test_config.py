"""Tests for global config management."""

from pathlib import Path

from autoresearch.config import (
    DefaultsConfig,
    DaemonConfig,
    GlobalConfig,
    ensure_autoresearch_dir,
    load_config,
    save_config,
)


class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, tmp_path):
        config = load_config(tmp_path / "nonexistent.yaml")
        assert config.defaults.model == "sonnet"
        assert config.defaults.max_experiments == 50
        assert config.daemon.poll_interval == "60s"

    def test_reads_existing_file(self, tmp_path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "defaults:\n  model: opus\n  max_experiments: 100\n"
        )
        config = load_config(cfg_path)
        assert config.defaults.model == "opus"
        assert config.defaults.max_experiments == 100

    def test_handles_empty_file(self, tmp_path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("")
        config = load_config(cfg_path)
        assert config == GlobalConfig()


class TestSaveConfig:
    def test_roundtrip(self, tmp_path):
        cfg_path = tmp_path / ".autoresearch" / "config.yaml"
        config = GlobalConfig(
            defaults=DefaultsConfig(model="opus", max_experiments=200),
            daemon=DaemonConfig(max_concurrent=4),
        )
        save_config(config, cfg_path)
        loaded = load_config(cfg_path)
        assert loaded.defaults.model == "opus"
        assert loaded.defaults.max_experiments == 200
        assert loaded.daemon.max_concurrent == 4


class TestEnsureDir:
    def test_creates_directory(self, tmp_path, monkeypatch):
        fake_dir = tmp_path / ".autoresearch"
        monkeypatch.setattr("autoresearch.config.AUTORESEARCH_DIR", fake_dir)
        result = ensure_autoresearch_dir()
        assert result == fake_dir
        assert fake_dir.is_dir()

    def test_idempotent(self, tmp_path, monkeypatch):
        fake_dir = tmp_path / ".autoresearch"
        monkeypatch.setattr("autoresearch.config.AUTORESEARCH_DIR", fake_dir)
        ensure_autoresearch_dir()
        ensure_autoresearch_dir()
        assert fake_dir.is_dir()


class TestConfigDefaults:
    def test_defaults_config_defaults(self):
        d = DefaultsConfig()
        assert d.model == "sonnet"
        assert d.budget_per_experiment == "10m"
        assert d.max_experiments == 50
        assert d.direction == "higher"

    def test_daemon_config_defaults(self):
        d = DaemonConfig()
        assert d.poll_interval == "60s"
        assert d.max_concurrent == 2
        assert d.log_level == "info"

    def test_global_config_has_both_sections(self):
        g = GlobalConfig()
        assert isinstance(g.defaults, DefaultsConfig)
        assert isinstance(g.daemon, DaemonConfig)


class TestLoadConfigExtra:
    def test_partial_config_fills_defaults(self, tmp_path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("defaults:\n  model: haiku\n")
        config = load_config(cfg_path)
        assert config.defaults.model == "haiku"
        assert config.defaults.max_experiments == 50  # default
        assert config.daemon.poll_interval == "60s"  # default

    def test_daemon_section_only(self, tmp_path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("daemon:\n  max_concurrent: 4\n")
        config = load_config(cfg_path)
        assert config.daemon.max_concurrent == 4
        assert config.defaults.model == "sonnet"  # default

    def test_save_creates_nested_dirs(self, tmp_path):
        cfg_path = tmp_path / "deep" / "nested" / "config.yaml"
        config = GlobalConfig()
        save_config(config, cfg_path)
        assert cfg_path.is_file()

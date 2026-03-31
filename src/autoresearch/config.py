"""Global config management (~/.autoresearch/config.yaml)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


AUTORESEARCH_DIR = Path.home() / ".autoresearch"
CONFIG_PATH = AUTORESEARCH_DIR / "config.yaml"
AGENTS_DIR = ".autoresearch/agents"


class DefaultsConfig(BaseModel):
    model: str = "sonnet"
    budget_per_experiment: str = "10m"
    max_experiments: int = 50
    direction: str = "higher"


class DaemonConfig(BaseModel):
    poll_interval: str = "60s"
    max_concurrent: int = 2
    log_level: str = "info"


class GlobalConfig(BaseModel):
    defaults: DefaultsConfig = DefaultsConfig()
    daemon: DaemonConfig = DaemonConfig()


def ensure_autoresearch_dir() -> Path:
    """Create ~/.autoresearch/ if it doesn't exist. Return path."""
    AUTORESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    return AUTORESEARCH_DIR


def load_config(config_path: Path | None = None) -> GlobalConfig:
    """Read config.yaml. Create with defaults if missing."""
    path = config_path or CONFIG_PATH
    if not path.is_file():
        return GlobalConfig()
    with open(path) as f:
        data = yaml.safe_load(f)
    if data is None:
        return GlobalConfig()
    return GlobalConfig.model_validate(data)


def save_config(config: GlobalConfig, config_path: Path | None = None) -> None:
    """Write config back to disk."""
    path = config_path or CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump()
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

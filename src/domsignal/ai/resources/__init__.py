"""Ресурсы AI-ядра: таксономия, лексикон и экспортированные схемы.

Каталог намеренно называется `resources`, а не `data`: корневой `.gitignore`
игнорирует любой `data/`, и ресурсы не попали бы ни в git, ни в wheel.
"""

from __future__ import annotations

from importlib.resources import files
from typing import Any

import yaml  # type: ignore[import-untyped]


def read_resource(name: str) -> str:
    """Текст ресурса пакета."""
    return (files(__package__) / name).read_text(encoding="utf-8")


def load_yaml_resource(name: str) -> Any:
    """Разобранный YAML-ресурс пакета."""
    return yaml.safe_load(read_resource(name))

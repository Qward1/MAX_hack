"""Правила опасности из другой ревизии git — для честного сравнения «до / после».

`load_danger(ref)` читает `src/domsignal/ai/rules/danger.py` на ревизии `ref`
(`git show`) и загружает его отдельным модулем. Остальные модули ядра
(контракты, сопоставление основ, нормализация) берутся текущие: D6 меняет
только правила опасности.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import tempfile
from types import ModuleType

ROOT = pathlib.Path(__file__).resolve().parents[1]
DANGER_PATH = "src/domsignal/ai/rules/danger.py"


def load_danger(ref: str) -> ModuleType:
    source = subprocess.run(
        ["git", "show", f"{ref}:{DANGER_PATH}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    directory = pathlib.Path(tempfile.mkdtemp(prefix="domsignal-rules-"))
    path = directory / "danger_ref.py"
    path.write_bytes(source)
    name = f"domsignal_danger_{ref.replace('/', '_').replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

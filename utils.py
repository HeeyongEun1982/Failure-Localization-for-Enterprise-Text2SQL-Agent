from __future__ import annotations

import os
import importlib.util
from types import ModuleType
from typing import Any

def load_module_from_path(module_name: str, file_path: str) -> ModuleType:
    import sys
    file_path = os.path.abspath(file_path)
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {module_name} from {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    try:
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    except Exception:
        del sys.modules[module_name]
        raise
    return mod

def load_db_storage(base_dir: str):
    return load_module_from_path("db_storage", os.path.join(base_dir, "0.db_storage.py"))

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType


_CACHED_MODULE: ModuleType | None = None


def locate_tushare_skill_root() -> Path:
    env_path = os.environ.get("TUSHARE_SKILL_ROOT", "").strip()
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path).expanduser())

    stock_skill_root = Path(__file__).resolve().parent
    candidates.append(stock_skill_root.parent / "skill-tushare-servicehub-assistant")
    candidates.append(stock_skill_root / "dependencies" / "skill-tushare-servicehub-assistant")

    for candidate in candidates:
        service_path = candidate / "scripts" / "tushare_service.py"
        if service_path.exists():
            return candidate.resolve()

    raise FileNotFoundError(
        "Unable to locate dependency skill 'skill-tushare-servicehub-assistant'. "
        "Set TUSHARE_SKILL_ROOT or install the dependency as a sibling skill directory."
    )


def load_tushare_service() -> ModuleType:
    global _CACHED_MODULE
    if _CACHED_MODULE is not None:
        return _CACHED_MODULE

    skill_root = locate_tushare_skill_root()
    service_path = skill_root / "scripts" / "tushare_service.py"
    spec = importlib.util.spec_from_file_location("skill_tushare_servicehub_service", service_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to load lower skill service module from {service_path}")

    module = importlib.util.module_from_spec(spec)
    scripts_dir = str((skill_root / "scripts").resolve())
    if scripts_dir not in os.sys.path:
        os.sys.path.insert(0, scripts_dir)
    spec.loader.exec_module(module)
    _CACHED_MODULE = module
    return module


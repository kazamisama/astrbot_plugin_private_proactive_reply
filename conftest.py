"""pytest bootstrap: make ``astrbot`` importable when running tests in isolation.

AstrBot normally injects its source tree into ``sys.path`` at runtime. When
running ``pytest`` standalone against this plugin, that injection never
happens and every ``import astrbot.api.star`` inside ``main.py`` blows up
with ``ModuleNotFoundError: No module named 'astrbot'``.

This conftest runs before any test module is collected. It tries to locate
the AstrBot source tree in this order:

1. The ``ASTRBOT_PATH`` environment variable, if it points to a directory
   that contains an ``astrbot/`` subdirectory.
2. The embedded python layout: ``<python>/../app`` next to the executable
   that pytest is using (matches the AstrBot Windows install layout).
3. The common default ``C:/application/AstrBot/backend/app``.

The detected path is prepended to ``sys.path`` so test code can
``import astrbot`` exactly the way the plugin does at runtime. If no path
is found the conftest stays silent and the original ``ModuleNotFoundError``
surfaces — that is the right signal for a misconfigured environment.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _discover_astrbot_path() -> Path | None:
    env = os.environ.get("ASTRBOT_PATH", "").strip()
    if env and Path(env, "astrbot").is_dir():
        return Path(env)

    exe = Path(sys.executable).resolve()
    candidate = exe.parent.parent / "app"
    if (candidate / "astrbot").is_dir():
        return candidate

    default = Path(r"C:/application/AstrBot/backend/app")
    if (default / "astrbot").is_dir():
        return default

    return None


astrbot_path = _discover_astrbot_path()
if astrbot_path is not None and str(astrbot_path) not in sys.path:
    sys.path.insert(0, str(astrbot_path))

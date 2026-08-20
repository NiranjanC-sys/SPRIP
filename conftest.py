"""Make the monorepo's source trees importable during tests.

The workspace packages (``packages/core``, ``analytics``) are not installed into
the virtualenv yet, and ``pyproject.toml`` lists app packages that do not exist,
so ``pip install -e .`` cannot succeed until every app lands. Rather than put
``sys.path`` surgery inside library modules - which would be invisible to anyone
reading an import and would break as soon as the package *is* installed - the
path wiring lives here, in the one file whose job is test collection.

Delete this file the day ``pip install -e .`` works.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

for _relative in ("packages/core/src", "analytics/src"):
    _path = str(_ROOT / _relative)
    if _path not in sys.path:
        sys.path.insert(0, _path)

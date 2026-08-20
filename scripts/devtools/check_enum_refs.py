"""Fail loudly on a model referencing an enum member that does not exist.

A typo'd ``SomeEnum.MEMBER`` in a ``default=`` surfaces as an ``AttributeError``
at import time - one per run, which is a slow way to find a dozen of them. This
walks the model modules and reports every bad reference at once.
"""

from __future__ import annotations

import pathlib
import re
import sys

import speaker_roi_core.enums as enums_module

ALIASES = {"DatasetAccessEnum": "DatasetAccess", "DatasetTypeEnum": "DatasetType"}
PATTERN = re.compile(r"\b([A-Z][A-Za-z0-9]*)\.([A-Z][A-Z0-9_]{2,})\b")
ROOTS = (
    "packages/core/src/speaker_roi_core",
    "apps/api/src",
    "apps/worker/src",
    "analytics/src",
)


def main() -> int:
    known = {cls.__name__: {member.name for member in cls} for cls in enums_module.PG_ENUMS}
    bad = 0
    for root in ROOTS:
        base_path = pathlib.Path(root)
        if not base_path.exists():
            continue
        for path in sorted(base_path.rglob("*.py")):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for cls_name, member in PATTERN.findall(line):
                    resolved = ALIASES.get(cls_name, cls_name)
                    if resolved in known and member not in known[resolved]:
                        valid = ", ".join(sorted(known[resolved]))
                        print(f"{path}:{lineno}: {cls_name}.{member} — valid: {valid}")
                        bad += 1
    print(f"invalid enum references: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

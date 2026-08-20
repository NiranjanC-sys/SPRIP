"""Shared domain core: vocabularies, ORM models and the tenant-isolation contract.

This package holds everything the API, the worker and the analytics library must
agree on. It deliberately imports no web framework and no task queue, so a model
invariant can be tested - and a migration generated - without standing up an
application.

``speaker_roi_core.models`` is not imported here. Importing it pulls in every
mapped class as a side effect on ``Base.metadata``, which is exactly what Alembic
and the schema tests want but is unnecessary weight for a caller that only needs
an enum. Callers that need the full metadata import ``speaker_roi_core.models``
explicitly.
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]

"""Analytics library for the HCP Speaker Program Impact & ROI Platform.

This package is deliberately free of any web-framework or ORM import (plan.md
§17: "Keep analytics code independent of FastAPI request objects and UI state").
Everything the API and the worker need is reached through plain callables and
plain data structures, so the same code is exercised by unit tests with
dictionaries and by production with a database behind an injected resolver.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"

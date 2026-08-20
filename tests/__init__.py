"""Test suite root. Packaged so that sibling helper modules can be imported
relatively (``from .conftest import ...``) instead of relying on rootdir path
insertion, which breaks the moment two test directories share a helper name."""

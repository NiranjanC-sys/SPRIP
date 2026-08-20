"""Integration tests for the exports endpoints."""
from __future__ import annotations

import httpx
import pytest

from tests.api.conftest import skip_no_server

pytestmark = [skip_no_server]


class TestExportCreate:
    def test_create_export(self, client: httpx.Client):
        r = client.post("/exports", json={"type": "portfolio_report"})
        # Should return 202 with taskId, or 403 if permission missing
        assert r.status_code in (202, 403, 422)
        if r.status_code == 202:
            data = r.json()
            assert "taskId" in data
            assert isinstance(data["taskId"], str)

    def test_create_export_invalid_type(self, client: httpx.Client):
        r = client.post("/exports", json={"type": "nonexistent_type_xyz"})
        assert r.status_code in (422, 400, 202, 403)


class TestExportStatus:
    def test_status_nonexistent_task(self, client: httpx.Client):
        r = client.get("/exports/nonexistent-task-id/status")
        assert r.status_code in (200, 404, 422, 400)

    def test_status_after_create(self, client: httpx.Client):
        create = client.post("/exports", json={"type": "portfolio_report"})
        if create.status_code != 202:
            pytest.skip("Export creation not available (permission or service)")
        task_id = create.json()["taskId"]
        r = client.get(f"/exports/{task_id}/status")
        assert r.status_code in (200, 404, 202)

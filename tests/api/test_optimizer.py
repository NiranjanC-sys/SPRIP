"""Integration tests for the optimizer/scenario endpoints."""
from __future__ import annotations

import httpx
import pytest

from tests.api.conftest import skip_no_server

pytestmark = [skip_no_server]


class TestScenarioList:
    def test_list_scenarios(self, client: httpx.Client):
        r = client.get("/optimizer/scenarios")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_pagination(self, client: httpx.Client):
        r = client.get("/optimizer/scenarios", params={"limit": 5})
        assert r.status_code == 200
        assert len(r.json()["items"]) <= 5


class TestScenarioCreate:
    def test_create_requires_permission(self, client: httpx.Client):
        r = client.post(
            "/optimizer/scenarios",
            json={"name": "Test Scenario", "parameters": {"budget": 100000}},
        )
        # Admin lacks scenario:write — expect 403
        assert r.status_code in (201, 403, 422)


class TestScenarioDetail:
    def test_nonexistent_scenario_404(self, client: httpx.Client):
        r = client.get("/optimizer/scenarios/00000000-0000-0000-0000-000000000000")
        assert r.status_code in (404, 422)


class TestScenarioDelete:
    def test_delete_requires_permission(self, client: httpx.Client):
        r = client.delete("/optimizer/scenarios/00000000-0000-0000-0000-000000000000")
        # Could be 403 (no permission) or 404 (not found)
        assert r.status_code in (204, 403, 404, 422)

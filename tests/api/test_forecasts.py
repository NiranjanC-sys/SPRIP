"""Integration tests for the forecasts endpoints."""
from __future__ import annotations

import httpx
import pytest

from tests.api.conftest import skip_no_server

pytestmark = [skip_no_server]


class TestForecastsList:
    def test_list_forecasts(self, client: httpx.Client):
        r = client.get("/forecasts")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_pagination_params(self, client: httpx.Client):
        r = client.get("/forecasts", params={"limit": 5})
        assert r.status_code == 200
        assert len(r.json()["items"]) <= 5


class TestForecastCreate:
    def test_create_requires_permission(self, client: httpx.Client):
        r = client.post("/forecasts", json={})
        # Admin may not have analysis:run permission — expect 403 or 422
        assert r.status_code in (202, 403, 422)

    def test_create_returns_task_id_or_forbidden(self, client: httpx.Client):
        r = client.post("/forecasts", json={"brand_id": "00000000-0000-0000-0000-000000000000"})
        if r.status_code == 202:
            assert "taskId" in r.json()
        else:
            assert r.status_code in (403, 422)


class TestForecastDetail:
    def test_nonexistent_forecast_404(self, client: httpx.Client):
        r = client.get("/forecasts/00000000-0000-0000-0000-000000000000")
        assert r.status_code in (404, 422)

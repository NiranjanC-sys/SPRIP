"""Integration tests for the ROI endpoints."""
from __future__ import annotations

import httpx
import pytest

from tests.api.conftest import skip_no_server

pytestmark = [skip_no_server]


class TestRoiResults:
    def test_list_results(self, client: httpx.Client):
        r = client.get("/roi/results")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) > 0

    def test_results_have_required_fields(self, client: httpx.Client):
        r = client.get("/roi/results")
        item = r.json()["items"][0]
        for field in ("id", "level", "benefitCostRatio"):
            assert field in item, f"Missing field: {field}"

    def test_filter_by_level(self, client: httpx.Client):
        r = client.get("/roi/results", params={"level": "EVENT"})
        assert r.status_code == 200
        items = r.json()["items"]
        for item in items:
            assert item["level"] == "EVENT"

    def test_filter_by_min_bcr(self, client: httpx.Client):
        r = client.get("/roi/results", params={"min_bcr": 5.0})
        assert r.status_code == 200
        items = r.json()["items"]
        for item in items:
            assert item["benefitCostRatio"] >= 5.0

    def test_pagination(self, client: httpx.Client):
        r1 = client.get("/roi/results", params={"limit": 2})
        assert r1.status_code == 200
        data1 = r1.json()
        assert len(data1["items"]) <= 2


class TestRoiSummary:
    def test_summary(self, client: httpx.Client):
        r = client.get("/roi/summary")
        assert r.status_code == 200
        data = r.json()
        assert "portfolioBcr" in data
        assert "totalSpend" in data
        assert data["portfolioBcr"] is not None
        assert isinstance(data["portfolioBcr"], (int, float))

    def test_summary_brands(self, client: httpx.Client):
        r = client.get("/roi/summary")
        data = r.json()
        if "brands" in data:
            assert isinstance(data["brands"], list)


class TestRoiResultDetail:
    def test_get_single_result(self, client: httpx.Client):
        listing = client.get("/roi/results", params={"limit": 1})
        items = listing.json()["items"]
        if not items:
            pytest.skip("No ROI results in database")
        result_id = items[0]["id"]
        r = client.get(f"/roi/results/{result_id}")
        assert r.status_code == 200
        assert r.json()["id"] == result_id

    def test_nonexistent_result_404(self, client: httpx.Client):
        r = client.get("/roi/results/00000000-0000-0000-0000-000000000000")
        assert r.status_code in (404, 422)

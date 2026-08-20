"""Integration tests for the dashboard endpoints."""
from __future__ import annotations

import httpx
import pytest

from tests.api.conftest import skip_no_server

pytestmark = [skip_no_server]


class TestDashboardStats:
    def test_returns_stats(self, client: httpx.Client):
        r = client.get("/dashboard/stats")
        assert r.status_code == 200
        data = r.json()
        assert "totalEvents" in data
        assert "totalHcps" in data
        assert "avgRoi" in data
        assert isinstance(data["totalEvents"], int)
        assert data["totalEvents"] > 0

    def test_avg_roi_populated(self, client: httpx.Client):
        r = client.get("/dashboard/stats")
        data = r.json()
        assert data["avgRoi"] is not None
        assert isinstance(data["avgRoi"], (int, float))
        assert data["avgRoi"] > 0


class TestRoiTrend:
    def test_returns_trend(self, client: httpx.Client):
        r = client.get("/dashboard/roi-trend")
        assert r.status_code == 200
        data = r.json()
        assert "data" in data
        assert isinstance(data["data"], dict)

    def test_trend_has_items(self, client: httpx.Client):
        r = client.get("/dashboard/roi-trend")
        data = r.json()
        trend = data["data"].get("trend", [])
        assert isinstance(trend, list)
        assert len(trend) > 0


class TestEngagement:
    def test_returns_engagement(self, client: httpx.Client):
        r = client.get("/dashboard/engagement")
        assert r.status_code == 200
        data = r.json()
        assert "data" in data
        assert isinstance(data["data"], dict)

    def test_engagement_has_buckets(self, client: httpx.Client):
        r = client.get("/dashboard/engagement")
        data = r.json()
        buckets = data["data"].get("buckets", [])
        assert isinstance(buckets, list)
        assert len(buckets) > 0


class TestUnauthenticated:
    def test_stats_requires_auth(self):
        r = httpx.get("http://localhost:8000/api/v1/dashboard/stats", timeout=5)
        assert r.status_code == 401

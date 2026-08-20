import { useState, useMemo, useCallback } from "react";
import { PageHeader } from "@/components/PageHeader";
import { DataTable } from "@/components/DataTable";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { Loader2, Plus } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import type { ForecastItem, PaginatedResponse, Brand } from "@/types/api";

const columns = [
  {
    key: "brandId",
    header: "Brand",
    render: (r: ForecastItem) => String(r.brandName ?? r.brandId ?? "-"),
  },
  {
    key: "periodStart",
    header: "Period Start",
    render: (r: ForecastItem) =>
      r.periodStart ? new Date(r.periodStart).toLocaleDateString() : "-",
  },
  {
    key: "periodEnd",
    header: "Period End",
    render: (r: ForecastItem) =>
      r.periodEnd ? new Date(r.periodEnd).toLocaleDateString() : "-",
  },
  {
    key: "predictedNrx",
    header: "Predicted NRx",
    render: (r: ForecastItem) =>
      r.predictedNrx != null ? Number(r.predictedNrx).toLocaleString() : "-",
  },
  {
    key: "predictedRevenue",
    header: "Predicted Revenue",
    render: (r: ForecastItem) =>
      r.predictedRevenue != null
        ? `$${Number(r.predictedRevenue).toLocaleString()}`
        : "-",
  },
  {
    key: "confidence",
    header: "Confidence Range",
    render: (r: ForecastItem) =>
      r.confidenceLow != null && r.confidenceHigh != null
        ? `${Number(r.confidenceLow).toLocaleString()} - ${Number(r.confidenceHigh).toLocaleString()}`
        : "-",
  },
  {
    key: "modelVersion",
    header: "Model",
    render: (r: ForecastItem) => String(r.modelVersion ?? "-"),
  },
];

export function ForecastsPage() {
  const { data, status, error } = useApi(() => api.forecasts(), []);
  const brandsResult = useApi(() => api.brands(), []);
  const [allItems, setAllItems] = useState<ForecastItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | undefined>();
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genBrandId, setGenBrandId] = useState("");
  const [genError, setGenError] = useState("");
  const [brandFilter, setBrandFilter] = useState<string>("All");

  const initialLoaded = data !== null;
  if (initialLoaded && allItems.length === 0 && (data?.items.length ?? 0) > 0) {
    setAllItems(data!.items);
    setNextCursor(data!.nextCursor ?? undefined);
    setTotal(data!.total);
  }

  const items = allItems.length > 0 ? allItems : data?.items ?? [];
  const brands: Brand[] = brandsResult.data?.items ?? [];

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const res: PaginatedResponse<ForecastItem> = await api.forecasts(nextCursor);
      setAllItems((prev) => [...prev, ...res.items]);
      setNextCursor(res.nextCursor ?? undefined);
      setTotal(res.total);
    } finally {
      setLoadingMore(false);
    }
  }, [nextCursor, loadingMore]);

  const handleGenerate = async () => {
    if (!genBrandId) {
      setGenError("Please select a brand");
      return;
    }
    setGenerating(true);
    setGenError("");
    try {
      await api.createForecast({ brandId: genBrandId });
      // Refresh data
      setAllItems([]);
      window.location.reload();
    } catch (err) {
      setGenError(err instanceof Error ? err.message : "Failed to generate forecast");
    } finally {
      setGenerating(false);
    }
  };

  const filtered = useMemo(() => {
    if (brandFilter === "All") return items;
    return items.filter((f) => f.brandId === brandFilter);
  }, [items, brandFilter]);

  // Build chart data from filtered items
  const chartData = filtered
    .filter((f) => f.periodStart)
    .sort((a, b) => (a.periodStart ?? "").localeCompare(b.periodStart ?? ""))
    .map((f) => ({
      period: f.periodStart ? new Date(f.periodStart).toLocaleDateString(undefined, { month: "short", year: "2-digit" }) : "",
      predicted: f.predictedNrx ?? 0,
      low: f.confidenceLow ?? 0,
      high: f.confidenceHigh ?? 0,
    }));

  const selectStyle: React.CSSProperties = {
    padding: "8px 12px",
    borderRadius: 8,
    border: "1px solid var(--color-border-default)",
    backgroundColor: "var(--color-bg-input)",
    color: "var(--color-text-primary)",
    fontSize: 14,
    outline: "none",
  };

  return (
    <div>
      <PageHeader
        title="Forecasts"
        description="Predicted Rx volumes and revenue forecasts"
      />

      {/* Generate Forecast panel */}
      <div
        style={{
          padding: 16,
          marginBottom: 24,
          borderRadius: 12,
          border: "1px solid var(--color-border-default)",
          backgroundColor: "var(--color-bg-card)",
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <select
          value={genBrandId}
          onChange={(e) => setGenBrandId(e.target.value)}
          style={selectStyle}
        >
          <option value="">Select brand...</option>
          {brands.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
        <button
          onClick={handleGenerate}
          disabled={generating}
          style={{
            padding: "8px 16px",
            borderRadius: 8,
            border: "none",
            backgroundColor: "var(--color-accent)",
            color: "var(--color-text-inverse)",
            fontSize: 14,
            fontWeight: 500,
            cursor: generating ? "not-allowed" : "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
            opacity: generating ? 0.7 : 1,
          }}
        >
          {generating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={16} />}
          Generate Forecast
        </button>
        {genError && (
          <span style={{ color: "var(--color-danger)", fontSize: 13 }}>{genError}</span>
        )}
      </div>

      {/* Brand filter */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <select
          value={brandFilter}
          onChange={(e) => setBrandFilter(e.target.value)}
          style={selectStyle}
        >
          <option value="All">All Brands</option>
          {brands.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      </div>

      {/* Chart */}
      {chartData.length > 0 && (
        <div
          style={{
            marginBottom: 24,
            padding: 16,
            borderRadius: 12,
            border: "1px solid var(--color-border-default)",
            backgroundColor: "var(--color-bg-card)",
          }}
        >
          <h3
            style={{
              fontSize: 14,
              fontWeight: 600,
              marginBottom: 16,
              color: "var(--color-text-primary)",
            }}
          >
            Predicted NRx Over Time
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
              <XAxis dataKey="period" tick={{ fontSize: 12, fill: "var(--color-text-secondary)" }} />
              <YAxis tick={{ fontSize: 12, fill: "var(--color-text-secondary)" }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "var(--color-bg-card)",
                  border: "1px solid var(--color-border-default)",
                  borderRadius: 8,
                  color: "var(--color-text-primary)",
                }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="predicted"
                name="Predicted NRx"
                stroke="var(--color-chart-1)"
                strokeWidth={2}
                dot={{ r: 3 }}
              />
              <Line
                type="monotone"
                dataKey="low"
                name="Low Confidence"
                stroke="var(--color-chart-3)"
                strokeWidth={1}
                strokeDasharray="4 4"
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="high"
                name="High Confidence"
                stroke="var(--color-chart-2)"
                strokeWidth={1}
                strokeDasharray="4 4"
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <DataTable
        columns={columns}
        data={status === "success" ? filtered : null}
        status={status}
        error={error}
        keyFn={(r) => r.id}
      />

      {status === "success" && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginTop: 16,
            fontSize: 13,
            color: "var(--color-text-secondary)",
          }}
        >
          <span>
            Showing {filtered.length} of {total || items.length}
          </span>
          {nextCursor && brandFilter === "All" && (
            <button
              onClick={loadMore}
              disabled={loadingMore}
              style={{
                padding: "6px 16px",
                borderRadius: 8,
                border: "1px solid var(--color-border-default)",
                backgroundColor: "var(--color-bg-card)",
                color: "var(--color-text-primary)",
                fontSize: 13,
                cursor: loadingMore ? "not-allowed" : "pointer",
                display: "flex",
                alignItems: "center",
                gap: 6,
                opacity: loadingMore ? 0.7 : 1,
              }}
            >
              {loadingMore && <Loader2 size={14} className="animate-spin" />}
              Load More
            </button>
          )}
        </div>
      )}
    </div>
  );
}

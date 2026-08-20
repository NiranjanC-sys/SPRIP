import { useState, useMemo, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { Search, Loader2 } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  Legend,
} from "recharts";
import type { Event, PaginatedResponse } from "@/types/api";

const STATUS_OPTIONS = ["All", "COMPLETED", "PLANNED", "CANCELLED"] as const;
const FALLBACK_COLORS = ["#6366f1", "#0ea5e9", "#22c55e", "#f59e0b", "#ef4444"];
const GRADE_COLORS: Record<string, string> = {
  STRONG: "var(--color-chart-3)",
  MODERATE: "var(--color-chart-1)",
  DIRECTIONAL: "var(--color-chart-4)",
  INSUFFICIENT: "var(--color-chart-5)",
};

const columns = [
  {
    key: "name",
    header: "Event",
    render: (r: Event) => (
      <Link to={`/events/${r.id}`} style={{ color: "var(--color-accent)" }} className="hover:underline">
        {r.name || r.id}
      </Link>
    ),
  },
  {
    key: "status",
    header: "Status",
    render: (r: Event) =>
      r.status ? <StatusBadge status={String(r.status)} /> : "-",
  },
  {
    key: "brandName",
    header: "Brand",
    render: (r: Event) => String(r.brandName ?? r.brandId ?? "-"),
  },
  {
    key: "venueCity",
    header: "Location",
    render: (r: Event) => String(r.venueCity || r.venueName || "-"),
  },
  {
    key: "eventDate",
    header: "Date",
    render: (r: Event) =>
      r.eventDate ? new Date(r.eventDate).toLocaleDateString() : "-",
  },
  {
    key: "plannedAttendance",
    header: "Attendance",
    render: (r: Event) => (r.plannedAttendance != null ? String(r.plannedAttendance) : "-"),
  },
];

function formatCurrency(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export function EventsPage() {
  const { user } = useAuth();
  const isAdmin = user?.roles?.includes("PHARMA_ADMIN") ?? false;
  const { data, status, error } = useApi(() => api.events(), [], "events-list");
  const brandsResult = useApi(() => api.brands(), [], "brands-list");
  const impactsResult = useApi(() => isAdmin ? api.impacts() : Promise.resolve({ items: [], total: 0 } as PaginatedResponse<never>), [isAdmin], isAdmin ? "impacts-list" : undefined);
  const forecastsResult = useApi(() => isAdmin ? api.forecasts() : Promise.resolve({ items: [], total: 0 } as PaginatedResponse<never>), [isAdmin], isAdmin ? "forecasts-list" : undefined);
  const [allItems, setAllItems] = useState<Event[]>([]);
  const [nextCursor, setNextCursor] = useState<string | undefined>();
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("All");
  const [brandFilter, setBrandFilter] = useState<string>("All");

  useEffect(() => {
    if (data && data.items.length > 0 && allItems.length === 0) {
      setAllItems(data.items);
      setNextCursor(data.nextCursor ?? undefined);
      setTotal(data.total ?? data.items.length);
    }
  }, [data]);

  const items = allItems.length > 0 ? allItems : data?.items ?? [];
  const brands = brandsResult.data?.items ?? [];

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const res: PaginatedResponse<Event> = await api.events(nextCursor);
      setAllItems((prev) => [...prev, ...res.items]);
      setNextCursor(res.nextCursor ?? undefined);
      setTotal(res.total);
    } finally {
      setLoadingMore(false);
    }
  }, [nextCursor, loadingMore]);

  const filtered = useMemo(() => {
    let result = items;
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter((r) => (r.name ?? "").toLowerCase().includes(q));
    }
    if (statusFilter !== "All") {
      result = result.filter(
        (r) => (r.status ?? "").toUpperCase() === statusFilter
      );
    }
    if (brandFilter !== "All") {
      result = result.filter(
        (r) => String((r as Record<string, unknown>).brandId ?? "") === brandFilter
      );
    }
    return result;
  }, [items, search, statusFilter, brandFilter]);

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
      <PageHeader title="Events" description="Speaker events and engagements" />

      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <div style={{ position: "relative", flex: 1, minWidth: 200, maxWidth: 400 }}>
          <Search
            size={16}
            style={{
              position: "absolute",
              left: 12,
              top: "50%",
              transform: "translateY(-50%)",
              color: "var(--color-text-tertiary)",
              pointerEvents: "none",
            }}
          />
          <input
            type="text"
            placeholder="Search events..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              ...selectStyle,
              width: "100%",
              paddingLeft: 36,
            }}
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={selectStyle}
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s === "All" ? "All Statuses" : s}
            </option>
          ))}
        </select>
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

      <DataTable
        columns={columns}
        data={status === "success" ? filtered : null}
        status={status}
        error={error}
        keyFn={(r) => r.id}
      />

      {/* Impact Analysis & Brand Forecast Charts — admin only */}
      {isAdmin && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
          {impactsResult.status === "loading" ? (
            <div className="rounded-xl border p-5 flex items-center justify-center py-16" style={{ backgroundColor: "var(--color-bg-card)", borderColor: "var(--color-border-default)" }}>
              <Loader2 size={24} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
            </div>
          ) : (
            <ImpactAnalysisChart impacts={impactsResult.data?.items ?? []} />
          )}
          {forecastsResult.status === "loading" ? (
            <div className="rounded-xl border p-5 flex items-center justify-center py-16" style={{ backgroundColor: "var(--color-bg-card)", borderColor: "var(--color-border-default)" }}>
              <Loader2 size={24} className="animate-spin" style={{ color: "var(--color-text-tertiary)" }} />
            </div>
          ) : (
            <BrandForecastChart forecasts={forecastsResult.data?.items ?? []} />
          )}
        </div>
      )}

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
          {nextCursor && !search.trim() && statusFilter === "All" && brandFilter === "All" && (
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

function ImpactAnalysisChart({ impacts }: { impacts: Record<string, unknown>[] }) {
  const { gradeData, topImpacts } = useMemo(() => {
    const gradeCounts: Record<string, number> = {};
    const sorted = [...impacts]
      .sort((a, b) => Math.abs(Number(b.att ?? 0)) - Math.abs(Number(a.att ?? 0)))
      .slice(0, 15);

    impacts.forEach((i) => {
      const g = String(i.evidenceGrade ?? "UNKNOWN");
      gradeCounts[g] = (gradeCounts[g] ?? 0) + 1;
    });

    return {
      gradeData: Object.entries(gradeCounts).map(([grade, count]) => ({ grade, count })),
      topImpacts: sorted.map((i) => ({
        name: String(i.eventId ?? "").substring(0, 8),
        att: Number(i.att ?? 0),
        incrementalNrx: Number(i.incrementalNrx ?? 0),
        grade: String(i.evidenceGrade ?? ""),
      })),
    };
  }, [impacts]);

  const tooltipStyle = {
    contentStyle: {
      backgroundColor: "var(--color-bg-card)",
      borderColor: "var(--color-border-default)",
      borderRadius: "8px",
      color: "var(--color-text-primary)",
      fontSize: "12px",
    },
  };

  if (impacts.length === 0) {
    return (
      <div className="rounded-xl border p-5" style={{ backgroundColor: "var(--color-bg-card)", borderColor: "var(--color-border-default)" }}>
        <h3 className="text-sm font-medium mb-3" style={{ color: "var(--color-text-secondary)" }}>Impact Analysis</h3>
        <div className="text-sm text-center py-12" style={{ color: "var(--color-text-tertiary)" }}>No impact data available</div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border p-5" style={{ backgroundColor: "var(--color-bg-card)", borderColor: "var(--color-border-default)" }}>
      <h3 className="text-sm font-medium mb-1" style={{ color: "var(--color-text-secondary)" }}>Impact Analysis</h3>
      <p className="text-xs mb-4" style={{ color: "var(--color-text-tertiary)" }}>
        ATT (Average Treatment Effect on Treated) across top events
      </p>

      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={topImpacts} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
          <XAxis dataKey="name" tick={{ fontSize: 10, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" />
          <YAxis tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" label={{ value: "ATT", angle: -90, position: "insideLeft", style: { fontSize: 11, fill: "var(--color-text-tertiary)" } }} />
          <Tooltip {...tooltipStyle} formatter={(value: number, name: string) => [value.toFixed(2), name === "att" ? "ATT" : name]} />
          <Bar dataKey="att" radius={[4, 4, 0, 0]}>
            {topImpacts.map((d, i) => (
              <Cell key={i} fill={GRADE_COLORS[d.grade] ?? FALLBACK_COLORS[i % FALLBACK_COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <div className="mt-4">
        <div className="text-xs font-medium mb-2" style={{ color: "var(--color-text-tertiary)" }}>Evidence Grade Distribution</div>
        <div className="flex gap-4 flex-wrap">
          {gradeData.map((g) => (
            <div key={g.grade} className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full" style={{ backgroundColor: GRADE_COLORS[g.grade] ?? "var(--color-text-tertiary)" }} />
              <span className="text-xs" style={{ color: "var(--color-text-secondary)" }}>
                {g.grade}: {g.count}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function BrandForecastChart({ forecasts }: { forecasts: Record<string, unknown>[] }) {
  const chartData = useMemo(() => {
    return forecasts.map((f) => ({
      brand: String(f.brandName ?? String(f.brandId ?? "").substring(0, 8)),
      predictedNrx: Number(f.predictedNrx ?? 0),
      confidenceLow: Number(f.confidenceLow ?? 0),
      confidenceHigh: Number(f.confidenceHigh ?? 0),
      predictedRevenue: Number(f.predictedRevenue ?? 0),
    }));
  }, [forecasts]);

  const tooltipStyle = {
    contentStyle: {
      backgroundColor: "var(--color-bg-card)",
      borderColor: "var(--color-border-default)",
      borderRadius: "8px",
      color: "var(--color-text-primary)",
      fontSize: "12px",
    },
  };

  if (forecasts.length === 0) {
    return (
      <div className="rounded-xl border p-5" style={{ backgroundColor: "var(--color-bg-card)", borderColor: "var(--color-border-default)" }}>
        <h3 className="text-sm font-medium mb-3" style={{ color: "var(--color-text-secondary)" }}>Brand Forecast</h3>
        <div className="text-sm text-center py-12" style={{ color: "var(--color-text-tertiary)" }}>No forecast data available</div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border p-5" style={{ backgroundColor: "var(--color-bg-card)", borderColor: "var(--color-border-default)" }}>
      <h3 className="text-sm font-medium mb-1" style={{ color: "var(--color-text-secondary)" }}>Brand Forecast</h3>
      <p className="text-xs mb-4" style={{ color: "var(--color-text-tertiary)" }}>
        Predicted NRx by brand with confidence intervals
      </p>

      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
          <XAxis dataKey="brand" tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" />
          <YAxis tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" label={{ value: "Predicted NRx", angle: -90, position: "insideLeft", style: { fontSize: 11, fill: "var(--color-text-tertiary)" } }} />
          <Tooltip
            {...tooltipStyle}
            formatter={(value: number, name: string) => {
              if (name === "predictedNrx") return [value.toFixed(2), "Predicted NRx"];
              if (name === "confidenceLow") return [value.toFixed(2), "CI Low"];
              if (name === "confidenceHigh") return [value.toFixed(2), "CI High"];
              return [value.toFixed(2), name];
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="confidenceLow" name="CI Low" stackId="ci" fill="var(--color-chart-2)" opacity={0.3} radius={[0, 0, 0, 0]} />
          <Bar dataKey="predictedNrx" name="Predicted NRx" fill="var(--color-chart-1)" radius={[4, 4, 0, 0]} />
          <Bar dataKey="confidenceHigh" name="CI High" fill="var(--color-chart-4)" opacity={0.3} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>

      <div className="mt-4">
        <div className="text-xs font-medium mb-2" style={{ color: "var(--color-text-tertiary)" }}>Revenue Forecast</div>
        <div className="grid grid-cols-2 gap-3">
          {chartData.map((d) => (
            <div key={d.brand} className="flex justify-between text-xs" style={{ color: "var(--color-text-secondary)" }}>
              <span>{d.brand}</span>
              <span className="font-medium">{formatCurrency(d.predictedRevenue)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

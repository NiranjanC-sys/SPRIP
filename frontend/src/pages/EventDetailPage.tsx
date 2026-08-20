import { useParams, Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { MetricCard } from "@/components/MetricCard";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { ArrowLeft, Loader2, AlertCircle, DollarSign, Users, TrendingUp, BarChart3 } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { useState, useEffect } from "react";

const FALLBACK_COLORS = ["#6366f1", "#0ea5e9", "#22c55e", "#f59e0b", "#ef4444"];

function formatCurrency(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export function EventDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data, status, error } = useApi(() => api.eventDetail(id!), [id]);
  const costs = useApi(() => api.eventCosts(id!), [id]);

  const [colors, setColors] = useState(FALLBACK_COLORS);
  useEffect(() => {
    const root = document.documentElement;
    const style = getComputedStyle(root);
    const c = [1, 2, 3, 4, 5]
      .map((n) => style.getPropertyValue(`--color-chart-${n}`).trim())
      .filter(Boolean);
    if (c.length === 5) setColors(c);
  }, []);

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--color-accent)" }} />
      </div>
    );
  }

  if (status === "error" || !data) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-2">
        <AlertCircle size={32} style={{ color: "var(--color-danger)" }} />
        <p className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
          {error ?? "Failed to load event details"}
        </p>
        <Link
          to="/events"
          className="text-sm mt-2 hover:underline"
          style={{ color: "var(--color-accent)" }}
        >
          Back to Events
        </Link>
      </div>
    );
  }

  const event = data;
  const costItems: Record<string, unknown>[] = costs.data?.items ?? event.costs ?? [];
  const attendeeList: Record<string, unknown>[] = event.attendees_list ?? event.attendeesList ?? [];
  const hasAttendeeData = attendeeList.length > 0;

  // Build cost breakdown chart data
  const costChartData = costItems.map((c) => ({
    category: String(c.category ?? c.name ?? c.type ?? "Other"),
    amount: Number(c.amount ?? c.cost ?? 0),
  }));

  const attendeeColumns = [
    { key: "name", header: "Name", render: (r: Record<string, unknown>) => String(r.name ?? r.hcpName ?? r.id) },
    { key: "specialty", header: "Specialty", render: (r: Record<string, unknown>) => String(r.specialty ?? "-") },
    { key: "role", header: "Role", render: (r: Record<string, unknown>) => String(r.role ?? "-") },
  ];

  const tooltipStyle = {
    contentStyle: {
      backgroundColor: "var(--color-bg-card)",
      borderColor: "var(--color-border-default)",
      borderRadius: "8px",
      color: "var(--color-text-primary)",
      fontSize: "12px",
    },
  };

  return (
    <div>
      <Link
        to="/events"
        className="inline-flex items-center gap-1 text-sm mb-4 hover:underline"
        style={{ color: "var(--color-accent)" }}
      >
        <ArrowLeft size={14} /> Back to Events
      </Link>

      <PageHeader
        title={event.name || event.id}
        description={[
          event.eventDate ? new Date(event.eventDate).toLocaleDateString() : null,
          event.format,
          event.venueCity || event.venueName,
        ]
          .filter(Boolean)
          .join(" | ")}
      >
        {event.status && <StatusBadge status={String(event.status)} />}
      </PageHeader>

      {/* Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
        <MetricCard
          label="Planned Attendance"
          value={event.plannedAttendance ?? 0}
          icon={Users}
        />
        <MetricCard
          label="Speaker Tier"
          value={String(event.speakerTier ?? "N/A")}
          icon={TrendingUp}
        />
        <MetricCard
          label="Format"
          value={String(event.format ?? "N/A")}
          icon={BarChart3}
        />
        <MetricCard
          label="Venue"
          value={String(event.venueCity || event.venueName || "N/A")}
          icon={DollarSign}
        />
      </div>

      {/* Cost Breakdown */}
      <div
        className="rounded-xl border p-5 mb-6"
        style={{
          backgroundColor: "var(--color-bg-card)",
          borderColor: "var(--color-border-default)",
        }}
      >
        <h3
          className="text-sm font-medium mb-4"
          style={{ color: "var(--color-text-secondary)" }}
        >
          Cost Breakdown
        </h3>
        {costChartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={costChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
              <XAxis
                dataKey="category"
                tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }}
                stroke="var(--color-border-default)"
              />
              <YAxis
                tick={{ fontSize: 12, fill: "var(--color-text-tertiary)" }}
                stroke="var(--color-border-default)"
                tickFormatter={(v) => formatCurrency(v)}
              />
              <Tooltip
                {...tooltipStyle}
                formatter={(value: number) => formatCurrency(value)}
              />
              <Bar dataKey="amount" radius={[4, 4, 0, 0]}>
                {costChartData.map((_, i) => (
                  <Cell key={i} fill={colors[i % colors.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div
            className="text-sm text-center py-12"
            style={{ color: "var(--color-text-tertiary)" }}
          >
            No cost breakdown data available
          </div>
        )}
      </div>

      {/* Impact card */}
      {(event.incrementalRx != null || event.grade != null) && (
        <div
          className="rounded-xl border p-5 mb-6"
          style={{
            backgroundColor: "var(--color-bg-card)",
            borderColor: "var(--color-border-default)",
          }}
        >
          <h3
            className="text-sm font-medium mb-3"
            style={{ color: "var(--color-text-secondary)" }}
          >
            Impact Analysis
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {event.incrementalRx != null && (
              <div>
                <div className="text-xs" style={{ color: "var(--color-text-tertiary)" }}>Incremental Rx</div>
                <div className="text-lg font-bold">{Number(event.incrementalRx).toFixed(1)}</div>
              </div>
            )}
            {event.grade != null && (
              <div>
                <div className="text-xs" style={{ color: "var(--color-text-tertiary)" }}>Grade</div>
                <div className="text-lg font-bold">{String(event.grade)}</div>
              </div>
            )}
            {event.confidence != null && (
              <div>
                <div className="text-xs" style={{ color: "var(--color-text-tertiary)" }}>Confidence</div>
                <div className="text-lg font-bold">{String(event.confidence)}</div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Attendees */}
      <div
        className="rounded-xl border p-5"
        style={{
          backgroundColor: "var(--color-bg-card)",
          borderColor: "var(--color-border-default)",
        }}
      >
        <h3
          className="text-sm font-medium mb-4"
          style={{ color: "var(--color-text-secondary)" }}
        >
          Attendees
        </h3>
        {hasAttendeeData ? (
          <DataTable
            columns={attendeeColumns}
            data={attendeeList}
            status="success"
            error={null}
            keyFn={(r) => String(r.id ?? r.hcpId ?? Math.random())}
          />
        ) : (
          <div
            className="text-sm text-center py-8"
            style={{ color: "var(--color-text-tertiary)" }}
          >
            Attendance data loading
          </div>
        )}
      </div>
    </div>
  );
}

import { useParams, Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { ArrowLeft, Loader2, AlertCircle } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 py-2">
      <span
        className="text-sm font-medium w-32 shrink-0"
        style={{ color: "var(--color-text-secondary)" }}
      >
        {label}
      </span>
      <span className="text-sm">{value}</span>
    </div>
  );
}

export function HCPDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data, status, error } = useApi(() => api.hcpDetail(id!), [id]);

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
          {error ?? "Failed to load HCP details"}
        </p>
        <Link
          to="/hcps"
          className="text-sm mt-2 hover:underline"
          style={{ color: "var(--color-accent)" }}
        >
          Back to HCPs
        </Link>
      </div>
    );
  }

  const hcp = data;
  const rxHistory: { month: string; nrx: number }[] = hcp.rxHistory ?? [];
  const eventsAttended: Record<string, unknown>[] = hcp.events ?? hcp.eventsAttended ?? [];

  const eventColumns = [
    { key: "name", header: "Event", render: (r: Record<string, unknown>) => String(r.name ?? r.eventName ?? r.id) },
    {
      key: "date",
      header: "Date",
      render: (r: Record<string, unknown>) =>
        r.date ? new Date(String(r.date)).toLocaleDateString() : "-",
    },
    {
      key: "status",
      header: "Status",
      render: (r: Record<string, unknown>) =>
        r.status ? <StatusBadge status={String(r.status)} /> : "-",
    },
    { key: "role", header: "Role", render: (r: Record<string, unknown>) => String(r.role ?? r.speakerRole ?? "-") },
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
        to="/hcps"
        className="inline-flex items-center gap-1 text-sm mb-4 hover:underline"
        style={{ color: "var(--color-accent)" }}
      >
        <ArrowLeft size={14} /> Back to HCPs
      </Link>

      <PageHeader
        title={hcp.name || hcp.id}
        description={[hcp.specialty, hcp.region, hcp.tier].filter(Boolean).join(" | ")}
      />

      {/* Info section */}
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
          Profile
        </h3>
        <InfoRow label="Specialty" value={String(hcp.specialty ?? "-")} />
        <InfoRow label="Region" value={String(hcp.region ?? "-")} />
        <InfoRow label="Tier" value={String(hcp.tier ?? "-")} />
        <InfoRow label="Email" value={String(hcp.email ?? "-")} />
        {hcp.segment && <InfoRow label="Segment" value={String(hcp.segment)} />}
        {hcp.npi && <InfoRow label="NPI" value={String(hcp.npi)} />}
      </div>

      {/* Rx History Chart */}
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
          Rx History
        </h3>
        {rxHistory.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={rxHistory}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
              <XAxis
                dataKey="month"
                tick={{ fontSize: 12, fill: "var(--color-text-tertiary)" }}
                stroke="var(--color-border-default)"
              />
              <YAxis
                tick={{ fontSize: 12, fill: "var(--color-text-tertiary)" }}
                stroke="var(--color-border-default)"
              />
              <Tooltip {...tooltipStyle} />
              <Line
                type="monotone"
                dataKey="nrx"
                stroke="var(--color-chart-1)"
                strokeWidth={2}
                dot={{ fill: "var(--color-chart-1)", r: 3 }}
                name="NRx"
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div
            className="text-sm text-center py-12"
            style={{ color: "var(--color-text-tertiary)" }}
          >
            No Rx history data available
          </div>
        )}
      </div>

      {/* Events Attended */}
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
          Events Attended
        </h3>
        <DataTable
          columns={eventColumns}
          data={eventsAttended.length > 0 ? eventsAttended : null}
          status="success"
          error={null}
          keyFn={(r) => String(r.id ?? r.eventId ?? Math.random())}
        />
      </div>
    </div>
  );
}

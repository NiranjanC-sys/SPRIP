import { useParams, Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { MetricCard } from "@/components/MetricCard";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/context/AuthContext";
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
  const { user } = useAuth();
  const isAdmin = user?.roles?.includes("PHARMA_ADMIN") ?? false;
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
  // Build cost breakdown chart data
  const costChartData = costItems.map((c) => ({
    category: String(c.category ?? c.name ?? c.type ?? "Other"),
    amount: Number(c.amount ?? c.cost ?? 0),
  }));

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

      {/* Impact Analysis & ROI Charts — admin only */}
      {isAdmin && (event.impact || event.roi) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Impact Analysis Chart */}
          {event.impact && (() => {
            const att = Number(event.impact.att);
            const ciLow = Number(event.impact.ciLow);
            const ciHigh = Number(event.impact.ciHigh);
            const incrNrx = Number(event.impact.incrementalValue);
            const pValue = Number(event.impact.pValue);
            const impactBarData = [
              { name: "ATT", value: att, fill: colors[0] },
              { name: "CI Low", value: ciLow, fill: colors[1] },
              { name: "CI High", value: ciHigh, fill: colors[2] },
            ];
            const groupData = [
              { name: "Treated", value: Number(event.impact.nTreated), fill: colors[0] },
              { name: "Control", value: Number(event.impact.nControl), fill: colors[1] },
            ];
            return (
              <div className="rounded-xl border p-5" style={{ backgroundColor: "var(--color-bg-card)", borderColor: "var(--color-border-default)" }}>
                <div className="flex items-center justify-between mb-1">
                  <h3 className="text-sm font-medium" style={{ color: "var(--color-text-secondary)" }}>Impact Analysis</h3>
                  <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: pValue < 0.05 ? "var(--color-chart-3)" : "var(--color-chart-4)", color: "#fff" }}>
                    {event.impact.grade}
                  </span>
                </div>
                <p className="text-xs mb-3" style={{ color: "var(--color-text-tertiary)" }}>
                  ATT: {att.toFixed(2)} | Incr. NRx: {incrNrx.toFixed(1)} | p={pValue.toFixed(4)}
                </p>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={impactBarData} layout="vertical" margin={{ top: 5, right: 20, left: 50, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
                    <XAxis type="number" tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" />
                    <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" width={55} />
                    <Tooltip {...tooltipStyle} formatter={(value: number) => value.toFixed(2)} />
                    <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                      {impactBarData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                <div className="mt-3">
                  <div className="text-xs font-medium mb-2" style={{ color: "var(--color-text-tertiary)" }}>Treatment vs Control Groups</div>
                  <ResponsiveContainer width="100%" height={100}>
                    <BarChart data={groupData} margin={{ top: 5, right: 20, left: 50, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
                      <XAxis type="number" tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" />
                      <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" width={55} />
                      <Tooltip {...tooltipStyle} />
                      <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                        {groupData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            );
          })()}

          {/* ROI Analysis Chart */}
          {event.roi && (() => {
            const totalCost = Number(event.roi.totalCost);
            const grossContrib = Number(event.roi.grossContribution);
            const netRoi = Number(event.roi.netRoi);
            const bcr = Number(event.roi.benefitCostRatio);
            const roiBarData = [
              { name: "Total Cost", value: totalCost, fill: colors[4] },
              { name: "Gross Contribution", value: grossContrib, fill: colors[2] },
              { name: "Net ROI", value: netRoi, fill: netRoi >= 0 ? colors[2] : colors[4] },
            ];
            return (
              <div className="rounded-xl border p-5" style={{ backgroundColor: "var(--color-bg-card)", borderColor: "var(--color-border-default)" }}>
                <div className="flex items-center justify-between mb-1">
                  <h3 className="text-sm font-medium" style={{ color: "var(--color-text-secondary)" }}>ROI Analysis</h3>
                  <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: "var(--color-chart-1)", color: "#fff" }}>
                    BCR: {bcr.toFixed(2)}x
                  </span>
                </div>
                <p className="text-xs mb-3" style={{ color: "var(--color-text-tertiary)" }}>
                  Evidence: {event.roi.evidenceGrade}
                </p>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={roiBarData} margin={{ top: 5, right: 20, left: 20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
                    <XAxis dataKey="name" tick={{ fontSize: 10, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" />
                    <YAxis tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" tickFormatter={(v) => formatCurrency(v)} />
                    <Tooltip {...tooltipStyle} formatter={(value: number) => formatCurrency(value)} />
                    <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                      {roiBarData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            );
          })()}
        </div>
      )}

      {/* Brand Forecast Chart — admin only */}
      {isAdmin && event.forecast && (() => {
        const pointEst = Number(event.forecast.pointEstimate);
        const piLow = Number(event.forecast.piLow);
        const piHigh = Number(event.forecast.piHigh);
        const expAttend = Number(event.forecast.expectedAttendance);
        const expNrx = Number(event.forecast.expectedIncrementalNrx);
        const expRoi = Number(event.forecast.expectedNetRoi);
        const forecastBarData = [
          { name: "PI Low", value: piLow },
          { name: "Predicted NRx", value: pointEst },
          { name: "PI High", value: piHigh },
        ];
        const expectationsData = [
          { name: "Attendance", value: expAttend, fill: colors[0] },
          { name: "Incr. NRx", value: expNrx, fill: colors[2] },
        ];
        return (
          <div className="rounded-xl border p-5 mb-6" style={{ backgroundColor: "var(--color-bg-card)", borderColor: "var(--color-border-default)" }}>
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-sm font-medium" style={{ color: "var(--color-text-secondary)" }}>Brand Forecast</h3>
              <span className="text-xs" style={{ color: "var(--color-text-tertiary)" }}>Expected Net ROI: {formatCurrency(expRoi)}</span>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-3">
              <div>
                <div className="text-xs font-medium mb-2" style={{ color: "var(--color-text-tertiary)" }}>Prediction Interval</div>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={forecastBarData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
                    <XAxis dataKey="name" tick={{ fontSize: 10, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" />
                    <YAxis tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" />
                    <Tooltip {...tooltipStyle} formatter={(value: number) => value.toFixed(2)} />
                    <Bar dataKey="value" fill={colors[0]} radius={[4, 4, 0, 0]}>
                      <Cell fill={colors[1]} />
                      <Cell fill={colors[0]} />
                      <Cell fill={colors[3]} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div>
                <div className="text-xs font-medium mb-2" style={{ color: "var(--color-text-tertiary)" }}>Expected Outcomes</div>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={expectationsData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
                    <XAxis dataKey="name" tick={{ fontSize: 10, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" />
                    <YAxis tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }} stroke="var(--color-border-default)" />
                    <Tooltip {...tooltipStyle} formatter={(value: number) => value.toFixed(1)} />
                    <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                      {expectationsData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Speakers */}
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
          Speakers
        </h3>
        {(event.speakers as Record<string, unknown>[] | undefined)?.length ? (
          <DataTable
            columns={[
              { key: "hcpId", header: "HCP ID", render: (r: Record<string, unknown>) => String(r.hcpId ?? r.id ?? "-") },
              { key: "tier", header: "Tier", render: (r: Record<string, unknown>) => r.tier ? <StatusBadge status={String(r.tier)} /> : "-" },
              { key: "speakingRole", header: "Role", render: (r: Record<string, unknown>) => String(r.speakingRole ?? "-") },
              { key: "honorariumAmount", header: "Honorarium", render: (r: Record<string, unknown>) => r.honorariumAmount != null ? `${formatCurrency(Number(r.honorariumAmount))} ${r.currency ?? ""}`.trim() : "-" },
            ]}
            data={event.speakers as Record<string, unknown>[]}
            status="success"
            error={null}
            keyFn={(r) => String(r.id ?? r.hcpId ?? Math.random())}
          />
        ) : (
          <div
            className="text-sm text-center py-8"
            style={{ color: "var(--color-text-tertiary)" }}
          >
            No speaker data available
          </div>
        )}
      </div>
    </div>
  );
}

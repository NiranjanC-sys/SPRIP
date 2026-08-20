import { useState, useEffect, useMemo } from "react";
import { PageHeader } from "@/components/PageHeader";
import { MetricCard } from "@/components/MetricCard";
import { DataTable } from "@/components/DataTable";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { DollarSign, TrendingUp, CalendarDays, Activity, Loader2 } from "lucide-react";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

const FALLBACK_COLORS = ["#6366f1", "#0ea5e9", "#22c55e", "#f59e0b", "#ef4444"];

function useChartColors() {
  const [colors, setColors] = useState(FALLBACK_COLORS);
  useEffect(() => {
    const root = document.documentElement;
    const style = getComputedStyle(root);
    const c = [1, 2, 3, 4, 5]
      .map((n) => style.getPropertyValue(`--color-chart-${n}`).trim())
      .filter(Boolean);
    if (c.length === 5) setColors(c);
  }, []);
  return colors;
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
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
        {title}
      </h3>
      {children}
    </div>
  );
}

function ChartLoading() {
  return (
    <div className="flex items-center justify-center py-16">
      <Loader2
        size={24}
        className="animate-spin"
        style={{ color: "var(--color-text-tertiary)" }}
      />
    </div>
  );
}

function ChartEmpty({ message }: { message: string }) {
  return (
    <div
      className="flex items-center justify-center py-16 text-sm"
      style={{ color: "var(--color-text-tertiary)" }}
    >
      {message}
    </div>
  );
}

function formatCurrency(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export function AnalyticsDashboardPage() {
  const colors = useChartColors();
  const [brandFilter, setBrandFilter] = useState<string>("All");

  const stats = useApi(() => api.dashboardStats(), []);
  const brandsResult = useApi(() => api.brands(), []);
  const impacts = useApi(() => api.impacts(), []);
  const roiResults = useApi(() => api.roiResults(), []);

  const roiTrend = useApi(() => api.dashboardRoiTrend(), []);
  const engagement = useApi(() => api.dashboardEngagement(), []);

  const brands = brandsResult.data?.items ?? [];

  const totalSpend = stats.data?.totalSpend ?? 0;
  const avgRoi = stats.data?.avgRoi ?? 0;
  const totalEvents = stats.data?.totalEvents ?? 0;
  const engagementRate = stats.data?.engagementRate ?? 0;

  // Build spend-by-brand from ROI results
  const spendByBrand = useMemo(() => {
    const items = roiResults.data?.items ?? [];
    const filtered = brandFilter !== "All"
      ? items.filter((r) => r.brandId === brandFilter)
      : items;
    const map = new Map<string, number>();
    filtered.forEach((r) => {
      const brand = String((r as Record<string, unknown>).brandName ?? r.brandId ?? "Unknown");
      map.set(brand, (map.get(brand) ?? 0) + (Number(r.totalCost) || 0));
    });
    return Array.from(map.entries())
      .map(([brand, spend]) => ({ brand, spend }))
      .sort((a, b) => b.spend - a.spend)
      .slice(0, 8);
  }, [roiResults.data, brandFilter]);

  const engagementDistribution = useMemo(() => {
    const buckets = engagement.data?.buckets ?? [];
    return buckets.map((b) => ({ level: b.bucket, count: b.count }));
  }, [engagement.data]);

  const engagementTotal = engagementDistribution.reduce((s, d) => s + d.count, 0);

  // Engagement by specialty
  const engagementBySpecialty = useMemo(() => {
    return (engagement.data?.bySpecialty ?? []).map((s) => ({
      specialty: s.specialty,
      engaged: Math.round(s.avgEvents * 100),
      total: 100,
    }));
  }, [engagement.data]);

  // ROI trend data
  const { trendData, brandNames } = useMemo(() => {
    const items = roiTrend.data?.trend ?? [];
    if (!items.length) return { trendData: [] as Record<string, unknown>[], brandNames: [] as string[] };
    const filteredItems = brandFilter !== "All"
      ? items.filter((i) => i.brand === brandFilter || brands.find((b) => b.id === brandFilter && b.name === i.brand))
      : items;
    const bNames = [...new Set(filteredItems.map((i) => i.brand))];
    const months = [...new Set(filteredItems.map((i) => i.month))].sort();
    const data = months.map((month) => {
      const point: Record<string, unknown> = { month };
      filteredItems.filter((i) => i.month === month).forEach((i) => {
        point[i.brand] = i.trx > 0 && i.spend > 0 ? +(i.trx / i.spend).toFixed(2) : 0;
      });
      return point;
    });
    return { trendData: data, brandNames: bNames };
  }, [roiTrend.data, brandFilter, brands]);

  // Top events by ROI from impacts
  const topEvents = useMemo(() => {
    const items = impacts.data?.items ?? [];
    let filtered = [...items].filter(
      (e: Record<string, unknown>) => e.incrementalNrx != null || e.att != null
    );
    if (brandFilter !== "All") {
      filtered = filtered.filter(
        (e: Record<string, unknown>) => String(e.brandId ?? "") === brandFilter
      );
    }
    return filtered.slice(0, 10);
  }, [impacts.data, brandFilter]);

  const topEventsColumns = [
    { key: "eventId", header: "Event", render: (r: Record<string, unknown>) => String(r.eventId ?? r.id ?? "-").slice(0, 8) + "..." },
    { key: "outcomeMetric", header: "Metric", render: (r: Record<string, unknown>) => String(r.outcomeMetric ?? "-") },
    { key: "att", header: "ATT", render: (r: Record<string, unknown>) => r.att != null ? Number(r.att).toFixed(2) : "-" },
    { key: "incrementalNrx", header: "Incr. NRx", render: (r: Record<string, unknown>) => r.incrementalNrx != null ? Number(r.incrementalNrx).toFixed(1) : "-" },
    { key: "evidenceGrade", header: "Grade", render: (r: Record<string, unknown>) => String(r.evidenceGrade ?? "-") },
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
        title="ROI Analytics"
        description="Speaker program performance and return on investment"
      />

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

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
        <MetricCard
          label="Total Spend"
          value={formatCurrency(totalSpend)}
          icon={DollarSign}
        />
        <MetricCard
          label="Avg ROI"
          value={avgRoi > 0 ? `${avgRoi.toFixed(1)}x` : "N/A"}
          icon={TrendingUp}
          trend={avgRoi > 1 ? "Positive" : undefined}
          trendUp={avgRoi > 1}
        />
        <MetricCard
          label="Events Analyzed"
          value={totalEvents}
          icon={CalendarDays}
        />
        <MetricCard
          label="Engagement Rate"
          value={engagementRate > 0 ? `${(engagementRate * 100).toFixed(0)}%` : "N/A"}
          icon={Activity}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <ChartCard title="ROI Trend by Brand">
          {roiTrend.status === "loading" ? (
            <ChartLoading />
          ) : trendData.length === 0 ? (
            <ChartEmpty message="No trend data available" />
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={trendData}>
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
                <Legend />
                {brandNames.map((brand, i) => (
                  <Area
                    key={brand}
                    type="monotone"
                    dataKey={brand}
                    stroke={colors[i % colors.length]}
                    fill={colors[i % colors.length]}
                    fillOpacity={0.15}
                    strokeWidth={2}
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard title="Spend by Brand">
          {roiResults.status === "loading" ? (
            <ChartLoading />
          ) : spendByBrand.length === 0 ? (
            <ChartEmpty message="No spend data available" />
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={spendByBrand}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
                <XAxis
                  dataKey="brand"
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
                <Bar dataKey="spend" radius={[4, 4, 0, 0]}>
                  {spendByBrand.map((_, i) => (
                    <Cell key={i} fill={colors[i % colors.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <ChartCard title="HCP Engagement Distribution">
          {engagement.status === "loading" ? (
            <ChartLoading />
          ) : engagementDistribution.length === 0 ? (
            <ChartEmpty message="No engagement data available" />
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={engagementDistribution}
                  dataKey="count"
                  nameKey="level"
                  cx="50%"
                  cy="50%"
                  innerRadius={70}
                  outerRadius={110}
                  paddingAngle={3}
                  label={({ level, percent }) =>
                    `${level} ${(percent * 100).toFixed(0)}%`
                  }
                >
                  {engagementDistribution.map((_, i) => (
                    <Cell key={i} fill={colors[i % colors.length]} />
                  ))}
                </Pie>
                <Tooltip {...tooltipStyle} />
                <Legend />
                <text
                  x="50%"
                  y="50%"
                  textAnchor="middle"
                  dominantBaseline="middle"
                  style={{ fill: "var(--color-text-primary)", fontSize: 22, fontWeight: 700 }}
                >
                  {engagementTotal}
                </text>
              </PieChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard title="Engagement by Specialty">
          {engagement.status === "loading" ? (
            <ChartLoading />
          ) : engagementBySpecialty.length === 0 ? (
            <ChartEmpty message="No specialty data available" />
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={engagementBySpecialty} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
                <XAxis
                  type="number"
                  tick={{ fontSize: 12, fill: "var(--color-text-tertiary)" }}
                  stroke="var(--color-border-default)"
                />
                <YAxis
                  dataKey="specialty"
                  type="category"
                  width={120}
                  tick={{ fontSize: 11, fill: "var(--color-text-tertiary)" }}
                  stroke="var(--color-border-default)"
                />
                <Tooltip {...tooltipStyle} />
                <Legend />
                <Bar dataKey="engaged" name="Engaged" fill={colors[0]} radius={[0, 4, 4, 0]} />
                <Bar dataKey="total" name="Total" fill={colors[1]} radius={[0, 4, 4, 0]} opacity={0.4} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>
      </div>

      <ChartCard title="Top Event Impacts">
        <DataTable
          columns={topEventsColumns}
          data={topEvents.length > 0 ? topEvents : null}
          status={impacts.status === "loading" ? "loading" : "success"}
          error={null}
          keyFn={(r) => String(r.id ?? Math.random())}
        />
      </ChartCard>
    </div>
  );
}

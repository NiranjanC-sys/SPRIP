import { useMemo } from "react";
import { Tag, Users, Megaphone, CalendarDays, TrendingUp, DollarSign } from "lucide-react";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { AreaChart, Area, ResponsiveContainer } from "recharts";

export function DashboardPage() {
  const { user } = useAuth();
  const brands = useApi(() => api.brands(), []);
  const hcps = useApi(() => api.hcps(), []);
  const campaigns = useApi(() => api.campaigns(), []);
  const events = useApi(() => api.events(), []);
  const dashStats = useApi(() => api.dashboardStats().catch(() => null), []);

  const brandCount = dashStats.data?.totalBrands ?? brands.data?.items.length ?? 0;
  const hcpCount = dashStats.data?.totalHcps ?? hcps.data?.items.length ?? 0;
  const campaignCount = dashStats.data?.totalCampaigns ?? campaigns.data?.items.length ?? 0;
  const eventCount = dashStats.data?.totalEvents ?? events.data?.items.length ?? 0;

  // Build a simple sparkline from event dates (count per month)
  const sparklineData = useMemo(() => {
    const items = events.data?.items ?? [];
    if (items.length === 0) return [];
    const byMonth = new Map<string, number>();
    items.forEach((e) => {
      if (e.date) {
        const d = new Date(e.date);
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
        byMonth.set(key, (byMonth.get(key) ?? 0) + 1);
      }
    });
    return Array.from(byMonth.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([month, count]) => ({ month, count }));
  }, [events.data]);

  return (
    <div>
      <PageHeader
        title={`Welcome, ${user?.user.displayName ?? "User"}`}
        description={
          user?.activeTenant
            ? `${user.activeTenant.name} — ${user.roles.join(", ")}`
            : "Platform overview"
        }
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 mb-4">
        <MetricCard label="Brands" value={brandCount} icon={Tag} />
        <MetricCard label="HCPs" value={hcpCount} icon={Users} />
        <MetricCard
          label="Campaigns"
          value={campaignCount}
          icon={Megaphone}
        />
        <MetricCard label="Events" value={eventCount} icon={CalendarDays} />
        <MetricCard
          label="Total Budget"
          value={formatCurrency(
            campaigns.data?.items.reduce(
              (sum, c) => sum + (Number(c.budget) || 0),
              0
            ) ?? 0
          )}
          icon={DollarSign}
        />
        <MetricCard
          label="Avg ROI"
          value={
            events.data?.items.length
              ? `${(
                  events.data.items.reduce(
                    (s, e) => s + (Number(e.roi) || 0),
                    0
                  ) / events.data.items.length
                ).toFixed(1)}x`
              : "N/A"
          }
          icon={TrendingUp}
        />
      </div>

      {/* Sparkline */}
      {sparklineData.length > 1 && (
        <div
          className="rounded-xl border p-4 mb-6"
          style={{
            backgroundColor: "var(--color-bg-card)",
            borderColor: "var(--color-border-default)",
          }}
        >
          <div
            className="text-xs font-medium mb-2"
            style={{ color: "var(--color-text-tertiary)" }}
          >
            Events over time
          </div>
          <ResponsiveContainer width="100%" height={80}>
            <AreaChart data={sparklineData}>
              <Area
                type="monotone"
                dataKey="count"
                stroke="var(--color-accent)"
                fill="var(--color-accent-soft)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <RecentSection title="Recent Brands">
          {brands.status === "loading" ? (
            <SkeletonRows />
          ) : (
            (brands.data?.items ?? []).slice(0, 5).map((b) => (
              <Row key={b.id} primary={b.name} secondary={String(b.code ?? "")} />
            ))
          )}
          {brands.status === "success" && brandCount === 0 && (
            <EmptyHint text="No brands yet. Create one to get started." />
          )}
        </RecentSection>

        <RecentSection title="Recent Events">
          {events.status === "loading" ? (
            <SkeletonRows />
          ) : (
            (events.data?.items ?? []).slice(0, 5).map((e) => (
              <Row
                key={e.id}
                primary={e.name}
                secondary={e.date ? new Date(e.date).toLocaleDateString() : ""}
                badge={e.status}
              />
            ))
          )}
          {events.status === "success" && eventCount === 0 && (
            <EmptyHint text="No events scheduled." />
          )}
        </RecentSection>
      </div>
    </div>
  );
}

function RecentSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="rounded-xl border"
      style={{
        backgroundColor: "var(--color-bg-card)",
        borderColor: "var(--color-border-default)",
      }}
    >
      <div
        className="px-5 py-3 border-b font-medium text-sm"
        style={{ borderColor: "var(--color-border-default)" }}
      >
        {title}
      </div>
      <div className="divide-y" style={{ borderColor: "var(--color-border-default)" }}>
        {children}
      </div>
    </div>
  );
}

function Row({
  primary,
  secondary,
  badge,
}: {
  primary: string;
  secondary: string;
  badge?: string;
}) {
  return (
    <div className="flex items-center justify-between px-5 py-3">
      <div>
        <div className="text-sm font-medium">{primary}</div>
        <div
          className="text-xs"
          style={{ color: "var(--color-text-tertiary)" }}
        >
          {secondary}
        </div>
      </div>
      {badge && (
        <span
          className="text-xs px-2 py-0.5 rounded-full"
          style={{
            backgroundColor: "var(--color-accent-soft)",
            color: "var(--color-accent)",
          }}
        >
          {badge}
        </span>
      )}
    </div>
  );
}

function SkeletonRows() {
  return (
    <>
      {[1, 2, 3].map((i) => (
        <div key={i} className="px-5 py-4">
          <div
            className="h-3 rounded w-1/2 mb-2 animate-pulse"
            style={{ backgroundColor: "var(--color-bg-tertiary)" }}
          />
          <div
            className="h-2 rounded w-1/4 animate-pulse"
            style={{ backgroundColor: "var(--color-bg-tertiary)" }}
          />
        </div>
      ))}
    </>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <div
      className="px-5 py-8 text-center text-sm"
      style={{ color: "var(--color-text-tertiary)" }}
    >
      {text}
    </div>
  );
}

function formatCurrency(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

import { useParams, Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { MetricCard } from "@/components/MetricCard";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { ArrowLeft, Loader2, AlertCircle, DollarSign, CalendarDays, TrendingUp, Target } from "lucide-react";

function formatCurrency(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export function CampaignDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data, status, error } = useApi(() => api.campaignDetail(id!), [id]);

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
          {error ?? "Failed to load campaign details"}
        </p>
        <Link
          to="/campaigns"
          className="text-sm mt-2 hover:underline"
          style={{ color: "var(--color-accent)" }}
        >
          Back to Campaigns
        </Link>
      </div>
    );
  }

  const campaign = data;
  const eventsList: Record<string, unknown>[] = campaign.events ?? [];
  const totalSpent = eventsList.reduce((s, e) => s + (Number(e.cost) || 0), 0);
  const avgRoi = eventsList.length
    ? eventsList.reduce((s, e) => s + (Number(e.roi) || 0), 0) / eventsList.length
    : 0;

  const eventColumns = [
    {
      key: "name",
      header: "Event",
      render: (r: Record<string, unknown>) => (
        <Link
          to={`/events/${r.id}`}
          style={{ color: "var(--color-accent)" }}
          className="hover:underline"
        >
          {String(r.name ?? r.id)}
        </Link>
      ),
    },
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
    {
      key: "attendees",
      header: "Attendees",
      render: (r: Record<string, unknown>) => String(r.attendees ?? "-"),
    },
    {
      key: "cost",
      header: "Cost",
      render: (r: Record<string, unknown>) =>
        r.cost != null ? `$${Number(r.cost).toLocaleString()}` : "-",
    },
    {
      key: "roi",
      header: "ROI",
      render: (r: Record<string, unknown>) =>
        r.roi != null ? `${Number(r.roi).toFixed(1)}x` : "-",
    },
  ];

  return (
    <div>
      <Link
        to="/campaigns"
        className="inline-flex items-center gap-1 text-sm mb-4 hover:underline"
        style={{ color: "var(--color-accent)" }}
      >
        <ArrowLeft size={14} /> Back to Campaigns
      </Link>

      <PageHeader
        title={campaign.name || campaign.id}
        description={[
          campaign.brandName ?? campaign.brandId,
          campaign.startDate
            ? `${new Date(campaign.startDate).toLocaleDateString()} - ${campaign.endDate ? new Date(campaign.endDate).toLocaleDateString() : "Ongoing"}`
            : null,
        ]
          .filter(Boolean)
          .join(" | ")}
      >
        {campaign.status && <StatusBadge status={String(campaign.status)} />}
      </PageHeader>

      {/* Summary metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
        <MetricCard
          label="Budget"
          value={campaign.budget != null ? formatCurrency(Number(campaign.budget)) : "N/A"}
          icon={DollarSign}
        />
        <MetricCard
          label="Total Spent"
          value={formatCurrency(totalSpent)}
          icon={Target}
        />
        <MetricCard
          label="Events"
          value={eventsList.length}
          icon={CalendarDays}
        />
        <MetricCard
          label="Avg ROI"
          value={avgRoi > 0 ? `${avgRoi.toFixed(1)}x` : "N/A"}
          icon={TrendingUp}
          trend={avgRoi > 1 ? "Positive" : undefined}
          trendUp={avgRoi > 1}
        />
      </div>

      {/* Campaign info */}
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
          Campaign Details
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-2">
          {campaign.brandName && (
            <div className="flex items-center gap-2 py-2">
              <span className="text-sm font-medium w-28 shrink-0" style={{ color: "var(--color-text-secondary)" }}>Brand</span>
              <span className="text-sm">{String(campaign.brandName)}</span>
            </div>
          )}
          {campaign.status && (
            <div className="flex items-center gap-2 py-2">
              <span className="text-sm font-medium w-28 shrink-0" style={{ color: "var(--color-text-secondary)" }}>Status</span>
              <StatusBadge status={String(campaign.status)} />
            </div>
          )}
          {campaign.startDate && (
            <div className="flex items-center gap-2 py-2">
              <span className="text-sm font-medium w-28 shrink-0" style={{ color: "var(--color-text-secondary)" }}>Start Date</span>
              <span className="text-sm">{new Date(campaign.startDate).toLocaleDateString()}</span>
            </div>
          )}
          {campaign.endDate && (
            <div className="flex items-center gap-2 py-2">
              <span className="text-sm font-medium w-28 shrink-0" style={{ color: "var(--color-text-secondary)" }}>End Date</span>
              <span className="text-sm">{new Date(campaign.endDate).toLocaleDateString()}</span>
            </div>
          )}
        </div>
      </div>

      {/* Events table */}
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
          Campaign Events
        </h3>
        <DataTable
          columns={eventColumns}
          data={eventsList.length > 0 ? eventsList : null}
          status="success"
          error={null}
          keyFn={(r) => String(r.id ?? Math.random())}
        />
      </div>
    </div>
  );
}

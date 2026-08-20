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
  const hasEvents = eventsList.length > 0;

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
      key: "eventDate",
      header: "Date",
      render: (r: Record<string, unknown>) =>
        r.eventDate ? new Date(String(r.eventDate)).toLocaleDateString() : "-",
    },
    {
      key: "status",
      header: "Status",
      render: (r: Record<string, unknown>) =>
        r.status ? <StatusBadge status={String(r.status)} /> : "-",
    },
    {
      key: "plannedAttendance",
      header: "Attendance",
      render: (r: Record<string, unknown>) => String(r.plannedAttendance ?? "-"),
    },
    {
      key: "impactGrade",
      header: "Impact",
      render: (r: Record<string, unknown>) => r.impactGrade ? <StatusBadge status={String(r.impactGrade)} /> : "-",
    },
    {
      key: "incrementalNrx",
      header: "Incr. NRx",
      render: (r: Record<string, unknown>) => r.incrementalNrx != null ? Number(r.incrementalNrx).toFixed(1) : "-",
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
          label="Planned Budget"
          value={campaign.plannedBudget != null ? formatCurrency(Number(campaign.plannedBudget)) : "N/A"}
          icon={DollarSign}
        />
        <MetricCard
          label="Brand"
          value={String(campaign.brandName ?? campaign.brandId ?? "N/A")}
          icon={Target}
        />
        <MetricCard
          label="Events"
          value={campaign.eventCount ?? eventsList.length}
          icon={CalendarDays}
        />
        <MetricCard
          label="Avg BCR"
          value={campaign.avgBcr != null ? `${Number(campaign.avgBcr).toFixed(2)}x` : "N/A"}
          icon={TrendingUp}
          trend={campaign.avgBcr > 1 ? "Positive" : undefined}
          trendUp={campaign.avgBcr > 1}
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

      {/* Campaign ROI Summary */}
      {(campaign.totalIncrementalNrx != null || campaign.avgBcr != null) && (
        <div className="rounded-xl border p-5 mb-6" style={{ backgroundColor: "var(--color-bg-card)", borderColor: "var(--color-border-default)" }}>
          <h3 className="text-sm font-medium mb-3" style={{ color: "var(--color-text-secondary)" }}>Campaign ROI Summary</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {campaign.plannedBudget != null && (
              <div>
                <div className="text-xs" style={{ color: "var(--color-text-tertiary)" }}>Total Spend</div>
                <div className="text-lg font-bold">{formatCurrency(Number(campaign.plannedBudget))}</div>
              </div>
            )}
            {campaign.totalIncrementalNrx != null && (
              <div>
                <div className="text-xs" style={{ color: "var(--color-text-tertiary)" }}>Total Incremental NRx</div>
                <div className="text-lg font-bold">{Number(campaign.totalIncrementalNrx).toFixed(1)}</div>
              </div>
            )}
            {campaign.avgBcr != null && (
              <div>
                <div className="text-xs" style={{ color: "var(--color-text-tertiary)" }}>Avg BCR</div>
                <div className="text-lg font-bold">{Number(campaign.avgBcr).toFixed(2)}x</div>
              </div>
            )}
            {campaign.evidenceSummary != null && (
              <div>
                <div className="text-xs" style={{ color: "var(--color-text-tertiary)" }}>Evidence Summary</div>
                <div className="text-lg font-bold">{campaign.evidenceSummary}</div>
              </div>
            )}
          </div>
        </div>
      )}

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
        {hasEvents ? (
          <DataTable
            columns={eventColumns}
            data={eventsList}
            status="success"
            error={null}
            keyFn={(r) => String(r.id ?? Math.random())}
          />
        ) : (
          <div
            className="text-sm text-center py-8"
            style={{ color: "var(--color-text-tertiary)" }}
          >
            No events data returned for this campaign
          </div>
        )}
      </div>
    </div>
  );
}

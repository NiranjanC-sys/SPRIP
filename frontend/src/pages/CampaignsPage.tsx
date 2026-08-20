import { PageHeader } from "@/components/PageHeader";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { Campaign } from "@/types/api";

const columns = [
  { key: "name", header: "Campaign" },
  {
    key: "status",
    header: "Status",
    render: (r: Campaign) =>
      r.status ? <StatusBadge status={String(r.status)} /> : "-",
  },
  {
    key: "startDate",
    header: "Start",
    render: (r: Campaign) =>
      r.startDate ? new Date(r.startDate).toLocaleDateString() : "-",
  },
  {
    key: "endDate",
    header: "End",
    render: (r: Campaign) =>
      r.endDate ? new Date(r.endDate).toLocaleDateString() : "-",
  },
  {
    key: "budget",
    header: "Budget",
    render: (r: Campaign) =>
      r.budget != null ? `$${Number(r.budget).toLocaleString()}` : "-",
  },
];

export function CampaignsPage() {
  const { data, status, error } = useApi(() => api.campaigns(), []);

  return (
    <div>
      <PageHeader
        title="Campaigns"
        description="Speaker engagement campaigns"
      />
      <DataTable
        columns={columns}
        data={data?.items ?? null}
        status={status}
        error={error}
        keyFn={(r) => r.id}
      />
    </div>
  );
}

import { PageHeader } from "@/components/PageHeader";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { Analysis } from "@/types/api";

const columns = [
  { key: "name", header: "Analysis", render: (r: Analysis) => String(r.name ?? r.id) },
  {
    key: "status",
    header: "Status",
    render: (r: Analysis) =>
      r.status ? <StatusBadge status={String(r.status)} /> : "-",
  },
  {
    key: "createdAt",
    header: "Created",
    render: (r: Analysis) =>
      r.createdAt ? new Date(r.createdAt).toLocaleDateString() : "-",
  },
];

export function AnalyticsPage() {
  const { data, status, error } = useApi(() => api.analyses(), []);

  return (
    <div>
      <PageHeader title="Analytics" description="ROI analyses and models" />
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

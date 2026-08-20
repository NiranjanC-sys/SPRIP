import { PageHeader } from "@/components/PageHeader";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { HCP } from "@/types/api";

const columns = [
  { key: "name", header: "Name" },
  { key: "specialty", header: "Specialty", render: (r: HCP) => String(r.specialty ?? "-") },
  {
    key: "tier",
    header: "Tier",
    render: (r: HCP) => r.tier ? <StatusBadge status={String(r.tier)} /> : "-",
  },
  { key: "region", header: "Region", render: (r: HCP) => String(r.region ?? "-") },
  { key: "email", header: "Email", render: (r: HCP) => String(r.email ?? "-") },
];

export function HCPsPage() {
  const { data, status, error } = useApi(() => api.hcps(), []);

  return (
    <div>
      <PageHeader
        title="Healthcare Professionals"
        description="Speaker panel and HCP management"
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

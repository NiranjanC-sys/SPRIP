import { PageHeader } from "@/components/PageHeader";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { Event } from "@/types/api";

const columns = [
  { key: "name", header: "Event" },
  {
    key: "status",
    header: "Status",
    render: (r: Event) =>
      r.status ? <StatusBadge status={String(r.status)} /> : "-",
  },
  { key: "location", header: "Location", render: (r: Event) => String(r.location ?? "-") },
  {
    key: "date",
    header: "Date",
    render: (r: Event) =>
      r.date ? new Date(r.date).toLocaleDateString() : "-",
  },
  {
    key: "attendees",
    header: "Attendees",
    render: (r: Event) => (r.attendees != null ? String(r.attendees) : "-"),
  },
  {
    key: "cost",
    header: "Cost",
    render: (r: Event) =>
      r.cost != null ? `$${Number(r.cost).toLocaleString()}` : "-",
  },
  {
    key: "roi",
    header: "ROI",
    render: (r: Event) =>
      r.roi != null ? `${Number(r.roi).toFixed(1)}x` : "-",
  },
];

export function EventsPage() {
  const { data, status, error } = useApi(() => api.events(), []);

  return (
    <div>
      <PageHeader title="Events" description="Speaker events and engagements" />
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

import { useState, useMemo, useCallback } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { Search, Loader2 } from "lucide-react";
import type { Event, PaginatedResponse } from "@/types/api";

const STATUS_OPTIONS = ["All", "COMPLETED", "PLANNED", "CANCELLED"] as const;

const columns = [
  {
    key: "name",
    header: "Event",
    render: (r: Event) => (
      <Link to={`/events/${r.id}`} style={{ color: "var(--color-accent)" }} className="hover:underline">
        {r.name || r.id}
      </Link>
    ),
  },
  {
    key: "status",
    header: "Status",
    render: (r: Event) =>
      r.status ? <StatusBadge status={String(r.status)} /> : "-",
  },
  {
    key: "brandName",
    header: "Brand",
    render: (r: Event) => String((r as Record<string, unknown>).brandName ?? (r as Record<string, unknown>).brandId ?? "-"),
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
  const brandsResult = useApi(() => api.brands(), []);
  const [allItems, setAllItems] = useState<Event[]>([]);
  const [nextCursor, setNextCursor] = useState<string | undefined>();
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("All");
  const [brandFilter, setBrandFilter] = useState<string>("All");

  const initialLoaded = data !== null;
  if (initialLoaded && allItems.length === 0 && (data?.items.length ?? 0) > 0) {
    setAllItems(data!.items);
    setNextCursor(data!.nextCursor ?? undefined);
    setTotal(data!.total);
  }

  const items = allItems.length > 0 ? allItems : data?.items ?? [];
  const brands = brandsResult.data?.items ?? [];

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const res: PaginatedResponse<Event> = await api.events(nextCursor);
      setAllItems((prev) => [...prev, ...res.items]);
      setNextCursor(res.nextCursor ?? undefined);
      setTotal(res.total);
    } finally {
      setLoadingMore(false);
    }
  }, [nextCursor, loadingMore]);

  const filtered = useMemo(() => {
    let result = items;
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter((r) => (r.name ?? "").toLowerCase().includes(q));
    }
    if (statusFilter !== "All") {
      result = result.filter(
        (r) => (r.status ?? "").toUpperCase() === statusFilter
      );
    }
    if (brandFilter !== "All") {
      result = result.filter(
        (r) => String((r as Record<string, unknown>).brandId ?? "") === brandFilter
      );
    }
    return result;
  }, [items, search, statusFilter, brandFilter]);

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
      <PageHeader title="Events" description="Speaker events and engagements" />

      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <div style={{ position: "relative", flex: 1, minWidth: 200, maxWidth: 400 }}>
          <Search
            size={16}
            style={{
              position: "absolute",
              left: 12,
              top: "50%",
              transform: "translateY(-50%)",
              color: "var(--color-text-tertiary)",
              pointerEvents: "none",
            }}
          />
          <input
            type="text"
            placeholder="Search events..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              ...selectStyle,
              width: "100%",
              paddingLeft: 36,
            }}
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={selectStyle}
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s === "All" ? "All Statuses" : s}
            </option>
          ))}
        </select>
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

      <DataTable
        columns={columns}
        data={status === "success" ? filtered : null}
        status={status}
        error={error}
        keyFn={(r) => r.id}
      />

      {status === "success" && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginTop: 16,
            fontSize: 13,
            color: "var(--color-text-secondary)",
          }}
        >
          <span>
            Showing {filtered.length} of {total || items.length}
          </span>
          {nextCursor && !search.trim() && statusFilter === "All" && brandFilter === "All" && (
            <button
              onClick={loadMore}
              disabled={loadingMore}
              style={{
                padding: "6px 16px",
                borderRadius: 8,
                border: "1px solid var(--color-border-default)",
                backgroundColor: "var(--color-bg-card)",
                color: "var(--color-text-primary)",
                fontSize: 13,
                cursor: loadingMore ? "not-allowed" : "pointer",
                display: "flex",
                alignItems: "center",
                gap: 6,
                opacity: loadingMore ? 0.7 : 1,
              }}
            >
              {loadingMore && <Loader2 size={14} className="animate-spin" />}
              Load More
            </button>
          )}
        </div>
      )}
    </div>
  );
}

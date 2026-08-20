import { useState, useMemo, useCallback } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { Search, Loader2 } from "lucide-react";
import type { HCP, PaginatedResponse } from "@/types/api";

const columns = [
  {
    key: "name",
    header: "Name",
    render: (r: HCP) => (
      <Link to={`/hcps/${r.id}`} style={{ color: "var(--color-accent)" }} className="hover:underline">
        {r.name || r.id}
      </Link>
    ),
  },
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
  const [allItems, setAllItems] = useState<HCP[]>([]);
  const [nextCursor, setNextCursor] = useState<string | undefined>();
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState("");

  // Sync initial data
  const initialLoaded = data !== null;
  if (initialLoaded && allItems.length === 0 && (data?.items.length ?? 0) > 0) {
    setAllItems(data!.items);
    setNextCursor(data!.nextCursor ?? undefined);
    setTotal(data!.total);
  }

  const items = allItems.length > 0 ? allItems : data?.items ?? [];

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const res: PaginatedResponse<HCP> = await api.hcps(nextCursor);
      setAllItems((prev) => [...prev, ...res.items]);
      setNextCursor(res.nextCursor ?? undefined);
      setTotal(res.total);
    } finally {
      setLoadingMore(false);
    }
  }, [nextCursor, loadingMore]);

  const filtered = useMemo(() => {
    if (!search.trim()) return items;
    const q = search.toLowerCase();
    return items.filter(
      (r) =>
        (r.name ?? "").toLowerCase().includes(q) ||
        (r.specialty ?? "").toLowerCase().includes(q)
    );
  }, [items, search]);

  return (
    <div>
      <PageHeader
        title="Healthcare Professionals"
        description="Speaker panel and HCP management"
      />

      <div style={{ marginBottom: 16, position: "relative", maxWidth: 400 }}>
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
          placeholder="Search by name or specialty..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            width: "100%",
            padding: "8px 12px 8px 36px",
            borderRadius: 8,
            border: "1px solid var(--color-border-default)",
            backgroundColor: "var(--color-bg-input)",
            color: "var(--color-text-primary)",
            fontSize: 14,
            outline: "none",
          }}
        />
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
          {nextCursor && !search.trim() && (
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

import { useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { Loader2 } from "lucide-react";
import type { RoiResult, PaginatedResponse } from "@/types/api";

const columns = [
  {
    key: "level",
    header: "Level",
    render: (r: RoiResult) => (
      <StatusBadge status={r.level ?? "-"} />
    ),
  },
  {
    key: "brandId",
    header: "Brand",
    render: (r: RoiResult) =>
      r.brandId ? (
        <Link to={`/brands`} style={{ color: "var(--color-accent)" }} className="hover:underline">
          {String(r.brandName ?? r.brandId)}
        </Link>
      ) : (
        "-"
      ),
  },
  {
    key: "eventId",
    header: "Event",
    render: (r: RoiResult) =>
      r.eventId ? (
        <Link to={`/events/${r.eventId}`} style={{ color: "var(--color-accent)" }} className="hover:underline">
          {String(r.eventName ?? r.eventId)}
        </Link>
      ) : (
        "-"
      ),
  },
  {
    key: "incrementalNrx",
    header: "Incr. NRx",
    render: (r: RoiResult) =>
      r.incrementalNrx != null ? Number(r.incrementalNrx).toFixed(1) : "-",
  },
  {
    key: "netRoi",
    header: "Net ROI",
    render: (r: RoiResult) =>
      r.netRoi != null ? `$${Number(r.netRoi).toLocaleString()}` : "-",
  },
  {
    key: "benefitCostRatio",
    header: "BCR",
    render: (r: RoiResult) =>
      r.benefitCostRatio != null
        ? `${Number(r.benefitCostRatio).toFixed(2)}x`
        : "-",
  },
  {
    key: "evidenceGrade",
    header: "Evidence Grade",
    render: (r: RoiResult) =>
      r.evidenceGrade ? (
        <StatusBadge status={r.evidenceGrade} />
      ) : (
        "-"
      ),
  },
];

export function RoiResultsPage() {
  const { data, status, error } = useApi(() => api.roiResults(), []);
  const [allItems, setAllItems] = useState<RoiResult[]>([]);
  const [nextCursor, setNextCursor] = useState<string | undefined>();
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);

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
      const res: PaginatedResponse<RoiResult> = await api.roiResults(nextCursor);
      setAllItems((prev) => [...prev, ...res.items]);
      setNextCursor(res.nextCursor ?? undefined);
      setTotal(res.total);
    } finally {
      setLoadingMore(false);
    }
  }, [nextCursor, loadingMore]);

  return (
    <div>
      <PageHeader
        title="ROI Results"
        description="Return on investment analysis across brands and events"
      />

      <DataTable
        columns={columns}
        data={status === "success" ? items : null}
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
            Showing {items.length} of {total || items.length}
          </span>
          {nextCursor && (
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

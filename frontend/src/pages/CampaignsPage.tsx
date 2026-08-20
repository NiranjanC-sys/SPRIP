import { useState, useMemo, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { Modal } from "@/components/Modal";
import { useApi } from "@/hooks/useApi";
import { useToast } from "@/context/ToastContext";
import { api } from "@/lib/api";
import { Plus, Search, Loader2 } from "lucide-react";
import type { Campaign, Brand, PaginatedResponse } from "@/types/api";

const columns = [
  {
    key: "name",
    header: "Campaign",
    render: (r: Campaign) => (
      <Link to={`/campaigns/${r.id}`} style={{ color: "var(--color-accent)" }} className="hover:underline">
        {r.name || r.id}
      </Link>
    ),
  },
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
    key: "plannedBudget",
    header: "Budget",
    render: (r: Campaign) =>
      r.plannedBudget != null ? `$${(r.plannedBudget || 0).toLocaleString()}` : "-",
  },
];

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 12px",
  borderRadius: 8,
  border: "1px solid var(--color-border-default)",
  backgroundColor: "var(--color-bg-input)",
  color: "var(--color-text-primary)",
  fontSize: 14,
};

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 13,
  fontWeight: 500,
  marginBottom: 4,
  color: "var(--color-text-secondary)",
};

export function CampaignsPage() {
  const { data, status, error, refetch } = useApi(() => api.campaigns(), [], "campaigns-list");
  const brandsResult = useApi(() => api.brands(), [], "brands-list");
  const { showToast } = useToast();
  const [showCreate, setShowCreate] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [search, setSearch] = useState("");
  const [allItems, setAllItems] = useState<Campaign[]>([]);
  const [nextCursor, setNextCursor] = useState<string | undefined>();
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);

  const [form, setForm] = useState({
    code: "",
    name: "",
    brandId: "",
    startDate: "",
    endDate: "",
    plannedBudget: "",
    currency: "USD",
    objective: "",
  });

  const updateField = (field: string, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const resetForm = () => {
    setForm({
      code: "",
      name: "",
      brandId: "",
      startDate: "",
      endDate: "",
      plannedBudget: "",
      currency: "USD",
      objective: "",
    });
  };

  // Sync initial data
  useEffect(() => {
    if (data && data.items.length > 0 && allItems.length === 0) {
      setAllItems(data.items);
      setNextCursor(data.nextCursor ?? undefined);
      setTotal(data.total ?? data.items.length);
    }
  }, [data]);

  const items = allItems.length > 0 ? allItems : data?.items ?? [];

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const res: PaginatedResponse<Campaign> = await api.campaigns(nextCursor);
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
    return items.filter((r) => (r.name ?? "").toLowerCase().includes(q));
  }, [items, search]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.code || !form.name) {
      showToast("Code and Name are required", "error");
      return;
    }
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        code: form.code,
        name: form.name,
        brandId: form.brandId || undefined,
        startDate: form.startDate || undefined,
        endDate: form.endDate || undefined,
        plannedBudget: form.plannedBudget
          ? Number(form.plannedBudget)
          : undefined,
        currency: form.currency || undefined,
        objective: form.objective || undefined,
      };
      await api.createCampaign(body);
      showToast("Campaign created successfully");
      setShowCreate(false);
      resetForm();
      setAllItems([]);
      refetch();
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : "Failed to create campaign",
        "error"
      );
    } finally {
      setSubmitting(false);
    }
  };

  const brands: Brand[] = brandsResult.data?.items ?? [];

  return (
    <div>
      <PageHeader
        title="Campaigns"
        description="Speaker engagement campaigns"
      >
        <button
          onClick={() => setShowCreate(true)}
          style={{
            backgroundColor: "var(--color-accent)",
            color: "var(--color-text-inverse)",
            padding: "8px 16px",
            borderRadius: 8,
            border: "none",
            fontSize: 14,
            fontWeight: 500,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <Plus size={16} />
          New Campaign
        </button>
      </PageHeader>

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
          placeholder="Search campaigns..."
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

      <Modal
        open={showCreate}
        onClose={() => {
          setShowCreate(false);
          resetForm();
        }}
        title="Create Campaign"
      >
        <form onSubmit={handleSubmit}>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <label style={labelStyle}>Code *</label>
              <input
                style={inputStyle}
                value={form.code}
                onChange={(e) => updateField("code", e.target.value)}
                placeholder="e.g. CAMP-2024-Q1"
              />
            </div>
            <div>
              <label style={labelStyle}>Name *</label>
              <input
                style={inputStyle}
                value={form.name}
                onChange={(e) => updateField("name", e.target.value)}
                placeholder="Campaign name"
              />
            </div>
            <div>
              <label style={labelStyle}>Brand</label>
              <select
                style={inputStyle}
                value={form.brandId}
                onChange={(e) => updateField("brandId", e.target.value)}
              >
                <option value="">Select a brand</option>
                {brands.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>Start Date</label>
                <input
                  type="date"
                  style={inputStyle}
                  value={form.startDate}
                  onChange={(e) => updateField("startDate", e.target.value)}
                />
              </div>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>End Date</label>
                <input
                  type="date"
                  style={inputStyle}
                  value={form.endDate}
                  onChange={(e) => updateField("endDate", e.target.value)}
                />
              </div>
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>Planned Budget</label>
                <input
                  type="number"
                  style={inputStyle}
                  value={form.plannedBudget}
                  onChange={(e) => updateField("plannedBudget", e.target.value)}
                  placeholder="0"
                />
              </div>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>Currency</label>
                <input
                  style={inputStyle}
                  value={form.currency}
                  onChange={(e) => updateField("currency", e.target.value)}
                  placeholder="USD"
                />
              </div>
            </div>
            <div>
              <label style={labelStyle}>Objective</label>
              <textarea
                style={{ ...inputStyle, minHeight: 60, resize: "vertical" }}
                value={form.objective}
                onChange={(e) => updateField("objective", e.target.value)}
                placeholder="Campaign objective"
              />
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
                marginTop: 8,
              }}
            >
              <button
                type="button"
                onClick={() => {
                  setShowCreate(false);
                  resetForm();
                }}
                style={{
                  padding: "8px 16px",
                  borderRadius: 8,
                  border: "1px solid var(--color-border-default)",
                  backgroundColor: "transparent",
                  color: "var(--color-text-primary)",
                  fontSize: 14,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                style={{
                  padding: "8px 16px",
                  borderRadius: 8,
                  border: "none",
                  backgroundColor: "var(--color-accent)",
                  color: "var(--color-text-inverse)",
                  fontSize: 14,
                  fontWeight: 500,
                  cursor: submitting ? "not-allowed" : "pointer",
                  opacity: submitting ? 0.7 : 1,
                }}
              >
                {submitting ? "Creating..." : "Create Campaign"}
              </button>
            </div>
          </div>
        </form>
      </Modal>
    </div>
  );
}

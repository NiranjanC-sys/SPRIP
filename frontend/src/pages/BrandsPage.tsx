import { useState, useMemo, useCallback } from "react";
import { PageHeader } from "@/components/PageHeader";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { api, ApiClientError } from "@/lib/api";
import type { Brand, PaginatedResponse } from "@/types/api";
import { Plus, Loader2, Search } from "lucide-react";

const columns = [
  { key: "code", header: "Code" },
  { key: "name", header: "Name" },
  {
    key: "therapeuticAreaCode",
    header: "Therapeutic Area",
    render: (r: Brand) => String(r.therapeuticAreaCode ?? "-"),
  },
  {
    key: "molecule",
    header: "Molecule",
    render: (r: Brand) => String(r.molecule ?? "-"),
  },
  {
    key: "isActive",
    header: "Status",
    render: (r: Brand) => (
      <StatusBadge status={r.isActive === false ? "Inactive" : "Active"} />
    ),
  },
  {
    key: "productCount",
    header: "Products",
    render: (r: Brand) => String(r.productCount ?? 0),
  },
];

export function BrandsPage() {
  const { data, status, error, refetch } = useApi(() => api.brands(), [], "brands-list");
  const [showForm, setShowForm] = useState(false);
  const [search, setSearch] = useState("");
  const [allItems, setAllItems] = useState<Brand[]>([]);
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
      const res: PaginatedResponse<Brand> = await api.brands(nextCursor);
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
        String(r.code ?? "").toLowerCase().includes(q)
    );
  }, [items, search]);

  return (
    <div>
      <PageHeader title="Brands" description="Manage your brand portfolio">
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          style={{
            backgroundColor: "var(--color-accent)",
            color: "var(--color-text-inverse)",
          }}
        >
          <Plus size={16} /> Add Brand
        </button>
      </PageHeader>

      {showForm && (
        <CreateBrandForm
          onCreated={() => {
            setShowForm(false);
            setAllItems([]);
            refetch();
          }}
          onCancel={() => setShowForm(false)}
        />
      )}

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
          placeholder="Search brands..."
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

function CreateBrandForm({
  onCreated,
  onCancel,
}: {
  onCreated: () => void;
  onCancel: () => void;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [area, setArea] = useState("cardiology");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await fetch("/api/v1/brands", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code,
          name,
          therapeuticAreaCode: area,
        }),
      }).then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.error?.message ?? `Error ${res.status}`);
        }
      });
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create brand");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="rounded-xl border p-5 mb-6 space-y-4"
      style={{
        backgroundColor: "var(--color-bg-card)",
        borderColor: "var(--color-border-default)",
      }}
    >
      <h3 className="font-medium text-sm">New Brand</h3>
      {error && (
        <div
          className="text-sm px-3 py-2 rounded-lg"
          style={{
            backgroundColor: "hsla(0, 84%, 60%, 0.1)",
            color: "var(--color-danger)",
          }}
        >
          {error}
        </div>
      )}
      <form onSubmit={handleSubmit} className="flex flex-wrap gap-3 items-end">
        <FormField label="Code" value={code} onChange={setCode} placeholder="cardiozen" />
        <FormField label="Name" value={name} onChange={setName} placeholder="CardioZen" />
        <FormField
          label="Therapeutic Area"
          value={area}
          onChange={setArea}
          placeholder="cardiology"
        />
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={loading || !code || !name}
            className="px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50 flex items-center gap-2"
            style={{
              backgroundColor: "var(--color-accent)",
              color: "var(--color-text-inverse)",
            }}
          >
            {loading && <Loader2 size={14} className="animate-spin" />}
            Create
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 rounded-lg text-sm border"
            style={{ borderColor: "var(--color-border-default)" }}
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

function FormField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="flex-1 min-w-[140px]">
      <label
        className="block text-xs font-medium mb-1"
        style={{ color: "var(--color-text-secondary)" }}
      >
        {label}
      </label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-3 py-2 rounded-lg border text-sm outline-none"
        style={{
          backgroundColor: "var(--color-bg-input)",
          borderColor: "var(--color-border-default)",
        }}
      />
    </div>
  );
}

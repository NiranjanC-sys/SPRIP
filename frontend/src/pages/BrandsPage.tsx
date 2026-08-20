import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { api, ApiClientError } from "@/lib/api";
import type { Brand } from "@/types/api";
import { Plus, Loader2 } from "lucide-react";

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
  const { data, status, error, refetch } = useApi(() => api.brands(), []);
  const [showForm, setShowForm] = useState(false);

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
            refetch();
          }}
          onCancel={() => setShowForm(false)}
        />
      )}

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

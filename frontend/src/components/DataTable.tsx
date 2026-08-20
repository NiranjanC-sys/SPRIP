import { Loader2, AlertCircle, Inbox } from "lucide-react";

interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => React.ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[] | null;
  status: "idle" | "loading" | "success" | "error";
  error?: string | null;
  keyFn: (row: T) => string;
}

export function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  status,
  error,
  keyFn,
}: DataTableProps<T>) {
  if (status === "loading") {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2
          size={24}
          className="animate-spin"
          style={{ color: "var(--color-text-tertiary)" }}
        />
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-2">
        <AlertCircle size={32} style={{ color: "var(--color-danger)" }} />
        <p className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
          {error ?? "Failed to load data"}
        </p>
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-2">
        <Inbox size={32} style={{ color: "var(--color-text-tertiary)" }} />
        <p className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
          No data available
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--color-border-default)" }}>
      <table className="w-full text-sm">
        <thead>
          <tr
            className="border-b"
            style={{
              backgroundColor: "var(--color-bg-secondary)",
              borderColor: "var(--color-border-default)",
            }}
          >
            {columns.map((col) => (
              <th
                key={col.key}
                className="text-left px-4 py-3 font-medium whitespace-nowrap"
                style={{ color: "var(--color-text-secondary)" }}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr
              key={keyFn(row)}
              className="border-b last:border-b-0 transition-colors"
              style={{
                borderColor: "var(--color-border-default)",
                backgroundColor: "var(--color-bg-card)",
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.backgroundColor =
                  "var(--color-bg-secondary)")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.backgroundColor =
                  "var(--color-bg-card)")
              }
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className="px-4 py-3 whitespace-nowrap"
                >
                  {col.render
                    ? col.render(row)
                    : String(row[col.key] ?? "-")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

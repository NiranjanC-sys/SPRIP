import type { LucideIcon } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: string | number;
  icon: LucideIcon;
  trend?: string;
  trendUp?: boolean;
}

export function MetricCard({ label, value, icon: Icon, trend, trendUp }: MetricCardProps) {
  return (
    <div
      className="rounded-xl border p-5 flex flex-col gap-3"
      style={{
        backgroundColor: "var(--color-bg-card)",
        borderColor: "var(--color-border-default)",
      }}
    >
      <div className="flex items-center justify-between">
        <span
          className="text-sm font-medium"
          style={{ color: "var(--color-text-secondary)" }}
        >
          {label}
        </span>
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center"
          style={{ backgroundColor: "var(--color-accent-soft)" }}
        >
          <Icon size={18} style={{ color: "var(--color-accent)" }} />
        </div>
      </div>
      <div className="flex items-end gap-2">
        <span className="text-2xl font-bold tracking-tight">{value}</span>
        {trend && (
          <span
            className="text-xs font-medium mb-1"
            style={{
              color: trendUp ? "var(--color-success)" : "var(--color-danger)",
            }}
          >
            {trend}
          </span>
        )}
      </div>
    </div>
  );
}

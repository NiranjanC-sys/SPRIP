interface StatusBadgeProps {
  status: string;
}

const statusColors: Record<string, { bg: string; text: string }> = {
  active: { bg: "var(--color-success)", text: "#fff" },
  completed: { bg: "var(--color-chart-2)", text: "#fff" },
  pending: { bg: "var(--color-warning)", text: "#fff" },
  cancelled: { bg: "var(--color-danger)", text: "#fff" },
  draft: { bg: "var(--color-text-tertiary)", text: "#fff" },
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const lower = status.toLowerCase();
  const colors = statusColors[lower] ?? {
    bg: "var(--color-bg-tertiary)",
    text: "var(--color-text-primary)",
  };

  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ backgroundColor: colors.bg, color: colors.text, opacity: 0.9 }}
    >
      {status}
    </span>
  );
}

import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api";
import { FileText, BarChart3, PieChart, Loader2, CheckCircle, AlertCircle, Download } from "lucide-react";
import type { ExportStatus } from "@/types/api";

interface ExportJob {
  exportType: string;
  label: string;
  icon: React.ElementType;
  description: string;
}

const EXPORT_TYPES: ExportJob[] = [
  {
    exportType: "portfolio_report",
    label: "Portfolio Report",
    icon: FileText,
    description: "Complete brand portfolio with campaigns and HCPs",
  },
  {
    exportType: "event_summary",
    label: "Event Summary",
    icon: BarChart3,
    description: "All events with attendance, cost, and status details",
  },
  {
    exportType: "roi_analysis",
    label: "ROI Analysis",
    icon: PieChart,
    description: "ROI results, BCR, and evidence grades across brands",
  },
];

interface ExportTask {
  taskId: string;
  exportType: string;
  status: string;
  downloadUrl?: string;
  error?: string;
}

export function ExportsPage() {
  const [tasks, setTasks] = useState<ExportTask[]>([]);
  const [triggering, setTriggering] = useState<string | null>(null);

  const triggerExport = async (exportType: string) => {
    setTriggering(exportType);
    try {
      const result: ExportStatus = await api.createExport({ exportType });
      setTasks((prev) => [
        {
          taskId: result.taskId,
          exportType,
          status: result.status,
          downloadUrl: result.downloadUrl,
        },
        ...prev,
      ]);
      // Start polling for status
      if (result.status !== "completed" && result.status !== "failed") {
        pollStatus(result.taskId, exportType);
      }
    } catch (err) {
      setTasks((prev) => [
        {
          taskId: `err-${Date.now()}`,
          exportType,
          status: "failed",
          error: err instanceof Error ? err.message : "Export failed",
        },
        ...prev,
      ]);
    } finally {
      setTriggering(null);
    }
  };

  const pollStatus = async (taskId: string, exportType: string) => {
    let attempts = 0;
    const maxAttempts = 30;
    const interval = 2000;

    const poll = async () => {
      if (attempts >= maxAttempts) {
        setTasks((prev) =>
          prev.map((t) =>
            t.taskId === taskId ? { ...t, status: "timeout", error: "Export timed out" } : t
          )
        );
        return;
      }
      attempts++;
      try {
        const result: ExportStatus = await api.exportStatus(taskId);
        setTasks((prev) =>
          prev.map((t) =>
            t.taskId === taskId
              ? { ...t, status: result.status, downloadUrl: result.downloadUrl }
              : t
          )
        );
        if (result.status !== "completed" && result.status !== "failed") {
          setTimeout(poll, interval);
        }
      } catch {
        setTimeout(poll, interval);
      }
    };
    setTimeout(poll, interval);
  };

  const cardStyle: React.CSSProperties = {
    padding: 20,
    borderRadius: 12,
    border: "1px solid var(--color-border-default)",
    backgroundColor: "var(--color-bg-card)",
    display: "flex",
    flexDirection: "column",
    gap: 12,
  };

  return (
    <div>
      <PageHeader
        title="Exports"
        description="Generate and download data exports"
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 16,
          marginBottom: 32,
        }}
      >
        {EXPORT_TYPES.map((exp) => {
          const Icon = exp.icon;
          const isTriggering = triggering === exp.exportType;
          return (
            <div key={exp.exportType} style={cardStyle}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: 10,
                    backgroundColor: "var(--color-accent-soft)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "var(--color-accent)",
                  }}
                >
                  <Icon size={20} />
                </div>
                <div>
                  <div
                    style={{
                      fontSize: 14,
                      fontWeight: 600,
                      color: "var(--color-text-primary)",
                    }}
                  >
                    {exp.label}
                  </div>
                  <div
                    style={{
                      fontSize: 12,
                      color: "var(--color-text-secondary)",
                    }}
                  >
                    {exp.description}
                  </div>
                </div>
              </div>
              <button
                onClick={() => triggerExport(exp.exportType)}
                disabled={isTriggering}
                style={{
                  padding: "8px 16px",
                  borderRadius: 8,
                  border: "none",
                  backgroundColor: "var(--color-accent)",
                  color: "var(--color-text-inverse)",
                  fontSize: 13,
                  fontWeight: 500,
                  cursor: isTriggering ? "not-allowed" : "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 6,
                  opacity: isTriggering ? 0.7 : 1,
                }}
              >
                {isTriggering ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Download size={14} />
                )}
                {isTriggering ? "Generating..." : "Generate Export"}
              </button>
            </div>
          );
        })}
      </div>

      {/* Export tasks history */}
      {tasks.length > 0 && (
        <div>
          <h3
            style={{
              fontSize: 14,
              fontWeight: 600,
              marginBottom: 12,
              color: "var(--color-text-primary)",
            }}
          >
            Export History
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {tasks.map((task) => {
              const expType = EXPORT_TYPES.find((e) => e.exportType === task.exportType);
              return (
                <div
                  key={task.taskId}
                  style={{
                    padding: "12px 16px",
                    borderRadius: 10,
                    border: "1px solid var(--color-border-default)",
                    backgroundColor: "var(--color-bg-card)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 12,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    {task.status === "completed" ? (
                      <CheckCircle size={16} style={{ color: "var(--color-success, #22c55e)" }} />
                    ) : task.status === "failed" || task.status === "timeout" ? (
                      <AlertCircle size={16} style={{ color: "var(--color-danger)" }} />
                    ) : (
                      <Loader2 size={16} className="animate-spin" style={{ color: "var(--color-accent)" }} />
                    )}
                    <div>
                      <span
                        style={{
                          fontSize: 13,
                          fontWeight: 500,
                          color: "var(--color-text-primary)",
                        }}
                      >
                        {expType?.label ?? task.exportType}
                      </span>
                      {task.error && (
                        <div style={{ fontSize: 12, color: "var(--color-danger)" }}>
                          {task.error}
                        </div>
                      )}
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span
                      style={{
                        fontSize: 12,
                        color: "var(--color-text-tertiary)",
                        textTransform: "capitalize",
                      }}
                    >
                      {task.status}
                    </span>
                    {task.downloadUrl && (
                      <a
                        href={task.downloadUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          padding: "4px 10px",
                          borderRadius: 6,
                          backgroundColor: "var(--color-accent)",
                          color: "var(--color-text-inverse)",
                          fontSize: 12,
                          fontWeight: 500,
                          textDecoration: "none",
                        }}
                      >
                        Download
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

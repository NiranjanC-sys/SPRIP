import { useState, useEffect, useCallback, Fragment } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { RefreshCw, ChevronDown, ChevronRight } from "lucide-react";
import { api } from "@/lib/api";
import type { UploadSession, ValidationIssue } from "@/types/api";

const statusColorMap: Record<string, { bg: string; text: string }> = {
  COMPLETED: { bg: "var(--color-success)", text: "#fff" },
  FAILED: { bg: "var(--color-danger)", text: "#fff" },
  PROCESSING: { bg: "var(--color-warning)", text: "#fff" },
  PENDING: { bg: "var(--color-text-tertiary)", text: "#fff" },
};

const severityColorMap: Record<string, { bg: string; text: string }> = {
  ERROR: { bg: "var(--color-danger)", text: "#fff" },
  WARNING: { bg: "var(--color-warning)", text: "#fff" },
  INFO: { bg: "var(--color-accent)", text: "#fff" },
};

function SeverityBadge({ severity }: { severity: string }) {
  const upper = severity.toUpperCase();
  const colors = severityColorMap[upper] ?? {
    bg: "var(--color-bg-tertiary)",
    text: "var(--color-text-primary)",
  };
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ backgroundColor: colors.bg, color: colors.text, opacity: 0.9 }}
    >
      {severity}
    </span>
  );
}

function UploadStatusBadge({ status }: { status: string }) {
  const upper = status.toUpperCase();
  const colors = statusColorMap[upper] ?? {
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

function SummaryCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  return (
    <div
      style={{
        flex: "1 1 160px",
        padding: "16px 20px",
        borderRadius: 8,
        border: "1px solid var(--color-border-default)",
        backgroundColor: "var(--color-bg-card)",
      }}
    >
      <p style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginBottom: 4 }}>
        {label}
      </p>
      <p
        style={{
          fontSize: 24,
          fontWeight: 700,
          color: color ?? "var(--color-text-primary)",
        }}
      >
        {value}
      </p>
    </div>
  );
}

function IssuesPanel({ sessionId }: { sessionId: string }) {
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.uploadSessionIssues(sessionId);
        if (!cancelled) setIssues(data.items ?? []);
      } catch {
        // ignore
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const thStyle: React.CSSProperties = {
    padding: "6px 10px",
    borderBottom: "1px solid var(--color-border-default)",
    backgroundColor: "var(--color-bg-secondary)",
    color: "var(--color-text-secondary)",
    fontWeight: 600,
    textAlign: "left" as const,
    fontSize: 12,
  };

  const tdStyle: React.CSSProperties = {
    padding: "6px 10px",
    borderBottom: "1px solid var(--color-border-default)",
    color: "var(--color-text-primary)",
    fontSize: 12,
  };

  if (loading) {
    return (
      <p style={{ padding: 12, fontSize: 12, color: "var(--color-text-tertiary)" }}>
        Loading issues...
      </p>
    );
  }

  if (issues.length === 0) {
    return (
      <p style={{ padding: 12, fontSize: 12, color: "var(--color-text-tertiary)" }}>
        No validation issues found.
      </p>
    );
  }

  return (
    <div style={{ overflow: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thStyle}>Row #</th>
            <th style={thStyle}>Field</th>
            <th style={thStyle}>Rule Code</th>
            <th style={thStyle}>Severity</th>
            <th style={thStyle}>Message</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue) => (
            <tr key={issue.id}>
              <td style={tdStyle}>{issue.rowNumber ?? "-"}</td>
              <td style={tdStyle}>{issue.fieldName ?? "-"}</td>
              <td style={tdStyle}>{issue.ruleCode}</td>
              <td style={tdStyle}>
                <SeverityBadge severity={issue.severity} />
              </td>
              <td style={{ ...tdStyle, whiteSpace: "normal", maxWidth: 400 }}>
                {issue.message ?? "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DataStewardPage() {
  const [sessions, setSessions] = useState<UploadSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.uploadSessions();
      setSessions(data.items ?? []);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const totalSessions = sessions.length;
  const completedCount = sessions.filter(
    (s) => s.status.toUpperCase() === "COMPLETED"
  ).length;
  const failedCount = sessions.filter(
    (s) => s.status.toUpperCase() === "FAILED"
  ).length;
  const totalRows = sessions.reduce((sum, s) => sum + (s.rowCount ?? 0), 0);
  const totalErrors = sessions.reduce((sum, s) => sum + (s.errorCount ?? 0), 0);

  const thStyle: React.CSSProperties = {
    padding: "8px 12px",
    borderBottom: "1px solid var(--color-border-default)",
    backgroundColor: "var(--color-bg-secondary)",
    color: "var(--color-text-secondary)",
    fontWeight: 600,
    textAlign: "left" as const,
    whiteSpace: "nowrap" as const,
    fontSize: 13,
  };

  const tdStyle: React.CSSProperties = {
    padding: "8px 12px",
    borderBottom: "1px solid var(--color-border-default)",
    color: "var(--color-text-primary)",
    whiteSpace: "nowrap" as const,
    fontSize: 13,
  };

  return (
    <div>
      <PageHeader
        title="Data Steward"
        description="Monitor upload sessions and data quality"
      />

      {/* Summary Cards */}
      <div className="flex flex-wrap gap-4" style={{ marginBottom: 24 }}>
        <SummaryCard label="Total Sessions" value={totalSessions} />
        <SummaryCard
          label="Completed"
          value={completedCount}
          color="var(--color-success)"
        />
        <SummaryCard
          label="Failed"
          value={failedCount}
          color="var(--color-danger)"
        />
        <SummaryCard label="Rows Processed" value={totalRows.toLocaleString()} />
        <SummaryCard
          label="Total Errors"
          value={totalErrors.toLocaleString()}
          color={totalErrors > 0 ? "var(--color-danger)" : undefined}
        />
      </div>

      {/* Sessions Table */}
      <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
        <h3
          style={{
            fontSize: 16,
            fontWeight: 600,
            color: "var(--color-text-primary)",
          }}
        >
          Upload Sessions
        </h3>
        <button
          onClick={loadSessions}
          disabled={loading}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "var(--color-text-tertiary)",
            padding: 4,
            display: "flex",
            alignItems: "center",
            gap: 4,
            fontSize: 13,
          }}
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {sessions.length === 0 && !loading ? (
        <p style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>
          No upload sessions found.
        </p>
      ) : (
        <div
          style={{
            borderRadius: 8,
            border: "1px solid var(--color-border-default)",
            overflow: "auto",
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ ...thStyle, width: 32 }} />
                <th style={thStyle}>Dataset Type</th>
                <th style={thStyle}>File Name</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Rows</th>
                <th style={thStyle}>Errors</th>
                <th style={thStyle}>Date</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => {
                const isExpanded = expandedId === s.id;
                return (
                  <Fragment key={s.id}>
                    <tr
                      onClick={() => setExpandedId(isExpanded ? null : s.id)}
                      style={{ cursor: "pointer" }}
                    >
                      <td style={{ ...tdStyle, width: 32, textAlign: "center" }}>
                        {isExpanded ? (
                          <ChevronDown size={14} />
                        ) : (
                          <ChevronRight size={14} />
                        )}
                      </td>
                      <td style={tdStyle}>{s.datasetType}</td>
                      <td style={tdStyle}>{s.fileName}</td>
                      <td style={tdStyle}>
                        <UploadStatusBadge status={s.status} />
                      </td>
                      <td style={tdStyle}>{s.rowCount ?? "-"}</td>
                      <td style={tdStyle}>{s.errorCount ?? "-"}</td>
                      <td style={tdStyle}>
                        {s.createdAt
                          ? new Date(s.createdAt).toLocaleDateString()
                          : "-"}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr>
                        <td
                          colSpan={7}
                          style={{
                            padding: 0,
                            backgroundColor: "var(--color-bg-secondary)",
                            borderBottom: "1px solid var(--color-border-default)",
                          }}
                        >
                          <div style={{ padding: "8px 16px" }}>
                            <p
                              style={{
                                fontSize: 13,
                                fontWeight: 600,
                                color: "var(--color-text-secondary)",
                                marginBottom: 8,
                              }}
                            >
                              Validation Issues
                            </p>
                            <IssuesPanel sessionId={s.id} />
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

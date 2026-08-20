import { useState, useRef, useCallback } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Upload, FileText, X } from "lucide-react";
import { useToast } from "@/context/ToastContext";

export function ImportPage() {
  const { showToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string[][] | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);

  const parseCSV = useCallback((text: string): string[][] => {
    const lines = text.split("\n").filter((l) => l.trim() !== "");
    return lines.slice(0, 6).map((line) => line.split(",").map((c) => c.trim()));
  }, []);

  const handleFile = useCallback(
    (f: File) => {
      if (!f.name.endsWith(".csv")) {
        showToast("Only .csv files are supported", "error");
        return;
      }
      setFile(f);
      const reader = new FileReader();
      reader.onload = (e) => {
        const text = e.target?.result as string;
        setPreview(parseCSV(text));
      };
      reader.readAsText(f);
    },
    [parseCSV, showToast]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files[0];
      if (f) handleFile(f);
    },
    [handleFile]
  );

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/v1/uploads/sessions", {
        method: "POST",
        credentials: "include",
        body: formData,
      });
      if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`);
      showToast("File uploaded successfully");
      setFile(null);
      setPreview(null);
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : "Upload failed",
        "error"
      );
    } finally {
      setUploading(false);
    }
  };

  const clearFile = () => {
    setFile(null);
    setPreview(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "8px 12px",
    borderRadius: 8,
    border: "1px solid var(--color-border-default)",
    backgroundColor: "var(--color-bg-input)",
    color: "var(--color-text-primary)",
    fontSize: 14,
  };

  return (
    <div>
      <PageHeader
        title="Data Import"
        description="Upload CSV files to import data"
      />

      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        style={{
          border: `2px dashed ${dragOver ? "var(--color-accent)" : "var(--color-border-default)"}`,
          borderRadius: 12,
          padding: "48px 24px",
          textAlign: "center",
          cursor: "pointer",
          backgroundColor: dragOver
            ? "var(--color-accent-soft)"
            : "var(--color-bg-secondary)",
          transition: "all 0.15s ease",
        }}
      >
        <Upload
          size={32}
          style={{
            color: "var(--color-text-tertiary)",
            margin: "0 auto 12px",
          }}
        />
        <p
          style={{
            fontSize: 14,
            fontWeight: 500,
            color: "var(--color-text-primary)",
          }}
        >
          Drag & drop a CSV file here, or click to browse
        </p>
        <p
          style={{
            fontSize: 13,
            color: "var(--color-text-tertiary)",
            marginTop: 4,
          }}
        >
          Only .csv files are accepted
        </p>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleFile(f);
          }}
        />
      </div>

      {/* Selected file info */}
      {file && (
        <div
          style={{
            marginTop: 16,
            padding: "12px 16px",
            borderRadius: 8,
            border: "1px solid var(--color-border-default)",
            backgroundColor: "var(--color-bg-card)",
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <FileText size={18} style={{ color: "var(--color-accent)" }} />
          <div style={{ flex: 1 }}>
            <p
              style={{
                fontSize: 14,
                fontWeight: 500,
                color: "var(--color-text-primary)",
              }}
            >
              {file.name}
            </p>
            <p
              style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}
            >
              {(file.size / 1024).toFixed(1)} KB
            </p>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              clearFile();
            }}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "var(--color-text-tertiary)",
              padding: 4,
            }}
          >
            <X size={16} />
          </button>
        </div>
      )}

      {/* Preview table */}
      {preview && preview.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h3
            style={{
              fontSize: 14,
              fontWeight: 600,
              marginBottom: 8,
              color: "var(--color-text-primary)",
            }}
          >
            Preview (first {Math.min(preview.length - 1, 5)} rows)
          </h3>
          <div
            style={{
              borderRadius: 8,
              border: "1px solid var(--color-border-default)",
              overflow: "auto",
            }}
          >
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr>
                  {preview[0]?.map((h, i) => (
                    <th
                      key={i}
                      style={{
                        ...inputStyle,
                        border: "none",
                        borderBottom: "1px solid var(--color-border-default)",
                        backgroundColor: "var(--color-bg-secondary)",
                        color: "var(--color-text-secondary)",
                        fontWeight: 600,
                        textAlign: "left",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.slice(1).map((row, ri) => (
                  <tr key={ri}>
                    {row.map((cell, ci) => (
                      <td
                        key={ci}
                        style={{
                          padding: "8px 12px",
                          borderBottom: "1px solid var(--color-border-default)",
                          color: "var(--color-text-primary)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Upload button */}
      {file && (
        <div style={{ marginTop: 16 }}>
          <button
            onClick={handleUpload}
            disabled={uploading}
            style={{
              backgroundColor: "var(--color-accent)",
              color: "var(--color-text-inverse)",
              padding: "10px 20px",
              borderRadius: 8,
              border: "none",
              fontSize: 14,
              fontWeight: 500,
              cursor: uploading ? "not-allowed" : "pointer",
              opacity: uploading ? 0.7 : 1,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <Upload size={16} />
            {uploading ? "Uploading..." : "Upload"}
          </button>
        </div>
      )}
    </div>
  );
}

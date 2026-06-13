

import React, { useState, useMemo, useRef } from "react";
import { Columns, Eye, Code2, Clipboard, Check, X, ShieldCheck, HelpCircle, AlertOctagon } from "lucide-react";

interface DiffViewerProps {
  originalCode: string;
  finalCode: string;
  filename: string | null;
  confidence: number;
  status: "clean" | "unresolved" | "no_progress" | "insecure";
  onApply: () => void;
  onReject: () => void;
}

interface DiffRow {
  type: "added" | "removed" | "normal";
  oldLine: string;
  newLine: string;
  oldNum?: number;
  newNum?: number;
}

// Custom LCS Diff Algorithm
function computeDiff(oldStr: string, newStr: string): DiffRow[] {
  const oldLines = oldStr.split("\n");
  const newLines = newStr.split("\n");
  const M = oldLines.length;
  const N = newLines.length;

  const dp: number[][] = Array(M + 1)
    .fill(0)
    .map(() => Array(N + 1).fill(0));

  for (let i = 1; i <= M; i++) {
    for (let j = 1; j <= N; j++) {
      if (oldLines[i - 1] === newLines[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  let i = M;
  let j = N;
  const result: DiffRow[] = [];

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      result.unshift({
        type: "normal",
        oldLine: oldLines[i - 1],
        newLine: newLines[j - 1],
        oldNum: i,
        newNum: j,
      });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      result.unshift({
        type: "added",
        oldLine: "",
        newLine: newLines[j - 1],
        newNum: j,
      });
      j--;
    } else {
      result.unshift({
        type: "removed",
        oldLine: oldLines[i - 1],
        newLine: "",
        oldNum: i,
      });
      i--;
    }
  }

  return result;
}

export function DiffViewer({
  originalCode,
  finalCode,
  filename,
  confidence,
  status,
  onApply,
  onReject
}: DiffViewerProps) {
  const [viewMode, setViewMode] = useState<"split" | "final">("split");
  const [copied, setCopied] = useState(false);

  const leftPaneRef = useRef<HTMLPreElement>(null);
  const rightPaneRef = useRef<HTMLPreElement>(null);

  const diffRows = useMemo(() => {
    return computeDiff(originalCode || "", finalCode || "");
  }, [originalCode, finalCode]);

  // Compute metrics
  const { addedCount, removedCount } = useMemo(() => {
    let add = 0;
    let del = 0;
    diffRows.forEach((row) => {
      if (row.type === "added") add++;
      if (row.type === "removed") del++;
    });
    return { addedCount: add, removedCount: del };
  }, [diffRows]);

  const totalChanges = addedCount + removedCount;

  const getStatusBadge = () => {
    switch (status) {
      case "clean":
        return { text: "✅ Validated", class: "badge-success" };
      case "insecure":
        return { text: "❌ Rejected", class: "badge-danger" };
      case "no_progress":
      case "unresolved":
      default:
        return { text: "⚠️ Review Recommended", class: "badge-warning" };
    }
  };

  const statusBadge = getStatusBadge();

  // Synchronize scrolls
  const handleLeftScroll = (e: React.UIEvent<HTMLPreElement>) => {
    const target = e.currentTarget;
    if (rightPaneRef.current) {
      if (rightPaneRef.current.scrollTop !== target.scrollTop) {
        rightPaneRef.current.scrollTop = target.scrollTop;
      }
      if (rightPaneRef.current.scrollLeft !== target.scrollLeft) {
        rightPaneRef.current.scrollLeft = target.scrollLeft;
      }
    }
  };

  const handleRightScroll = (e: React.UIEvent<HTMLPreElement>) => {
    const target = e.currentTarget;
    if (leftPaneRef.current) {
      if (leftPaneRef.current.scrollTop !== target.scrollTop) {
        leftPaneRef.current.scrollTop = target.scrollTop;
      }
      if (leftPaneRef.current.scrollLeft !== target.scrollLeft) {
        leftPaneRef.current.scrollLeft = target.scrollLeft;
      }
    }
  };

  // Generate copyable unified diff string
  const handleCopyDiff = () => {
    const header = `--- a/${filename || "source.py"}\n+++ b/${filename || "source.py"}\n`;
    const diffBody = diffRows
      .map((row) => {
        if (row.type === "added") return `+${row.newLine}`;
        if (row.type === "removed") return `-${row.oldLine}`;
        return ` ${row.newLine}`;
      })
      .join("\n");
    
    navigator.clipboard.writeText(header + diffBody);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* 1. Metadata Bar above Diff */}
      <div className="diff-meta-bar">
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <span>
            Lines Changed: <strong style={{ color: "white" }}>{totalChanges} lines</strong>
          </span>
          <span style={{ color: "var(--text-secondary)" }}>|</span>
          <span>
            Confidence: <strong style={{ color: "white" }}>{(confidence * 100).toFixed(0)}%</strong>
          </span>
        </div>
        <span className={`badge ${statusBadge.class}`} style={{ fontSize: "0.75rem", padding: "0.25rem 0.5rem" }}>
          {statusBadge.text}
        </span>
      </div>

      {/* 2. Main Diff View Box */}
      <div className="diff-viewer" style={{ flex: 1, borderTopLeftRadius: 0, borderTopRightRadius: 0, borderBottomLeftRadius: 0, borderBottomRightRadius: 0, borderBottom: "none" }}>
        <div className="diff-header" style={{ borderTop: "none" }}>
          <div className="diff-title">
            <Code2 size={14} color="var(--accent-primary)" />
            <span>Unified Code Comparison</span>
          </div>

          <div style={{ display: "flex", gap: "0.375rem" }}>
            <button
              type="button"
              className={`btn ${viewMode === "split" ? "btn-primary" : "btn-secondary"}`}
              style={{ padding: "0.25rem 0.5rem", fontSize: "0.725rem", borderRadius: "4px" }}
              onClick={() => setViewMode("split")}
            >
              <Columns size={10} />
              Side-by-Side
            </button>
            <button
              type="button"
              className={`btn ${viewMode === "final" ? "btn-primary" : "btn-secondary"}`}
              style={{ padding: "0.25rem 0.5rem", fontSize: "0.725rem", borderRadius: "4px" }}
              onClick={() => setViewMode("final")}
            >
              <Eye size={10} />
              Show Repaired
            </button>
          </div>
        </div>

        {viewMode === "split" ? (
          <div className="diff-columns">
            {/* Left Pane (Original Code) */}
            <div className="diff-pane">
              <div className="diff-pane-title">Before (Original)</div>
              <pre
                ref={leftPaneRef}
                onScroll={handleLeftScroll}
                className="code-pre"
                style={{ padding: "0.5rem" }}
              >
                {diffRows.map((row, idx) => {
                  const isRemoved = row.type === "removed";
                  const isAdded = row.type === "added";
                  
                  return (
                    <div
                      key={`left-${idx}`}
                      className={`diff-line ${isRemoved ? "deletion" : ""} ${isAdded ? "spacer-line" : ""}`}
                      style={{ minHeight: "1.25rem" }}
                    >
                      <div className="diff-line-num" style={{ fontSize: "0.75rem", width: "2rem", paddingRight: "0.5rem" }}>{row.oldNum || ""}</div>
                      <div className="diff-line-content" style={{ fontSize: "0.75rem", paddingLeft: "0.5rem", display: "flex", alignItems: "center" }}>
                        <span style={{
                          color: isRemoved ? "var(--status-error)" : "transparent",
                          marginRight: "0.375rem",
                          width: "0.625rem",
                          display: "inline-block",
                          userSelect: "none",
                          fontWeight: 700
                        }}>
                          {isRemoved ? "-" : " "}
                        </span>
                        {isAdded ? "" : row.oldLine || " "}
                      </div>
                    </div>
                  );
                })}
              </pre>
            </div>

            {/* Right Pane (Repaired Code) */}
            <div className="diff-pane">
              <div className="diff-pane-title">After (Patched)</div>
              <pre
                ref={rightPaneRef}
                onScroll={handleRightScroll}
                className="code-pre"
                style={{ padding: "0.5rem" }}
              >
                {diffRows.map((row, idx) => {
                  const isAdded = row.type === "added";
                  const isRemoved = row.type === "removed";

                  return (
                    <div
                      key={`right-${idx}`}
                      className={`diff-line ${isAdded ? "addition" : ""} ${isRemoved ? "spacer-line" : ""}`}
                      style={{ minHeight: "1.25rem" }}
                    >
                      <div className="diff-line-num" style={{ fontSize: "0.75rem", width: "2rem", paddingRight: "0.5rem" }}>{row.newNum || ""}</div>
                      <div className="diff-line-content" style={{ fontSize: "0.75rem", paddingLeft: "0.5rem", display: "flex", alignItems: "center" }}>
                        <span style={{
                          color: isAdded ? "var(--status-clean)" : "transparent",
                          marginRight: "0.375rem",
                          width: "0.625rem",
                          display: "inline-block",
                          userSelect: "none",
                          fontWeight: 700
                        }}>
                          {isAdded ? "+" : " "}
                        </span>
                        {isRemoved ? "" : row.newLine || " "}
                      </div>
                    </div>
                  );
                })}
              </pre>
            </div>
          </div>
        ) : (
          <div className="diff-pane" style={{ borderTop: "1px solid var(--border-color)" }}>
            <pre className="code-pre" style={{ padding: "0.5rem" }}>
              {finalCode.split("\n").map((line, idx) => (
                <div key={idx} className="diff-line">
                  <div className="diff-line-num" style={{ fontSize: "0.75rem", width: "2rem", paddingRight: "0.5rem" }}>{idx + 1}</div>
                  <div className="diff-line-content" style={{ fontSize: "0.75rem", paddingLeft: "0.5rem" }}>{line || " "}</div>
                </div>
              ))}
            </pre>
          </div>
        )}
      </div>

      {/* 3. Action Bar below Diff */}
      <div className="diff-actions-bar">
        <button
          type="button"
          className="btn btn-secondary"
          style={{ padding: "0.4rem 0.75rem" }}
          onClick={handleCopyDiff}
        >
          {copied ? <Check size={14} color="var(--status-clean)" /> : <Clipboard size={14} />}
          {copied ? "Copied!" : "Copy Diff"}
        </button>
        <button
          type="button"
          className="btn btn-danger"
          style={{ padding: "0.4rem 0.75rem" }}
          onClick={onReject}
        >
          <X size={14} />
          Reject
        </button>
        <button
          type="button"
          className="btn btn-primary"
          style={{ padding: "0.4rem 0.75rem", display: status === "insecure" ? "none" : "inline-flex" }}
          onClick={onApply}
        >
          <Check size={14} />
          Apply Patch
        </button>
      </div>

      <style>{`
        .spacer-line {
          background-color: rgba(255, 255, 255, 0.005);
          opacity: 0.15;
        }
      `}</style>
    </div>
  );
}

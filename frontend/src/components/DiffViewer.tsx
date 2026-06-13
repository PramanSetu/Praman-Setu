import React, { useState, useMemo } from "react";
import { Columns, Eye, Code2 } from "lucide-react";

interface DiffViewerProps {
  originalCode: string;
  finalCode: string;
  filename: string | null;
}

interface DiffRow {
  type: "added" | "removed" | "normal";
  oldLine: string;
  newLine: string;
  oldNum?: number;
  newNum?: number;
}

// Zero-dependency Longest Common Subsequence (LCS) Diff
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

export function DiffViewer({ originalCode, finalCode, filename }: DiffViewerProps) {
  const [viewMode, setViewMode] = useState<"split" | "final">("split");

  const diffRows = useMemo(() => {
    return computeDiff(originalCode || "", finalCode || "");
  }, [originalCode, finalCode]);

  return (
    <div className="diff-viewer">
      <div className="diff-header">
        <div className="diff-title">
          <Code2 size={16} color="var(--accent-primary)" />
          <span>{filename || "code_diff.py"}</span>
        </div>

        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            type="button"
            className={`btn ${viewMode === "split" ? "btn-primary" : "btn-secondary"}`}
            style={{ padding: "0.375rem 0.75rem", fontSize: "0.75rem" }}
            onClick={() => setViewMode("split")}
          >
            <Columns size={12} />
            Side-by-Side Diff
          </button>
          <button
            type="button"
            className={`btn ${viewMode === "final" ? "btn-primary" : "btn-secondary"}`}
            style={{ padding: "0.375rem 0.75rem", fontSize: "0.75rem" }}
            onClick={() => setViewMode("final")}
          >
            <Eye size={12} />
            Show Clean Repaired
          </button>
        </div>
      </div>

      {viewMode === "split" ? (
        <div className="diff-columns">
          {/* Left Pane (Original Code) */}
          <div className="diff-pane">
            <div className="diff-pane-title">Original (Before)</div>
            <pre className="code-pre">
              {diffRows.map((row, idx) => {
                const isRemoved = row.type === "removed";
                const isAdded = row.type === "added";
                
                return (
                  <div
                    key={`left-${idx}`}
                    className={`diff-line ${isRemoved ? "deletion" : ""} ${isAdded ? "spacer-line" : ""}`}
                    style={{ minHeight: "1.6rem" }}
                  >
                    <div className="diff-line-num">{row.oldNum || ""}</div>
                    <div className="diff-line-content">
                      {isAdded ? "" : row.oldLine || " "}
                    </div>
                  </div>
                );
              })}
            </pre>
          </div>

          {/* Right Pane (Repaired Code) */}
          <div className="diff-pane">
            <div className="diff-pane-title">Repaired (After)</div>
            <pre className="code-pre">
              {diffRows.map((row, idx) => {
                const isAdded = row.type === "added";
                const isRemoved = row.type === "removed";

                return (
                  <div
                    key={`right-${idx}`}
                    className={`diff-line ${isAdded ? "addition" : ""} ${isRemoved ? "spacer-line" : ""}`}
                    style={{ minHeight: "1.6rem" }}
                  >
                    <div className="diff-line-num">{row.newNum || ""}</div>
                    <div className="diff-line-content">
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
          <pre className="code-pre">
            {finalCode.split("\n").map((line, idx) => (
              <div key={idx} className="diff-line">
                <div className="diff-line-num">{idx + 1}</div>
                <div className="diff-line-content">{line || " "}</div>
              </div>
            ))}
          </pre>
        </div>
      )}

      <style>{`
        .spacer-line {
          background-color: rgba(255, 255, 255, 0.01);
          opacity: 0.3;
        }
      `}</style>
    </div>
  );
}

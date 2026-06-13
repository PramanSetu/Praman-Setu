import React, { useState } from "react";
import { RepairV2Result } from "../hooks/useApi";
import { Terminal, Shield, List, ChevronDown, ChevronUp, AlertCircle, FileCode, CheckCircle, Flame } from "lucide-react";

interface SandboxReportProps {
  result: RepairV2Result | null;
}

export function SandboxReport({ result }: SandboxReportProps) {
  const [openAttemptIdx, setOpenAttemptIdx] = useState<number | null>(0);

  if (!result) {
    return (
      <div className="glass-panel" style={{ textAlign: "center", padding: "2rem", color: "var(--text-secondary)" }}>
        <p>No sandbox validation telemetry available for this run.</p>
      </div>
    );
  }

  const { ledger, attempts } = result;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {/* Metrics Row */}
      <div className="metric-grid">
        <div className="metric-card">
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600, textTransform: "uppercase" }}>
            Total Passes
          </span>
          <div className="metric-val">{result.passes}</div>
        </div>
        <div className="metric-card">
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600, textTransform: "uppercase" }}>
            Compiles
          </span>
          <div className="metric-val" style={{ color: ledger.code_compiles ? "var(--status-clean)" : "var(--status-error)" }}>
            {ledger.code_compiles ? "Yes" : "No"}
          </div>
        </div>
        <div className="metric-card">
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600, textTransform: "uppercase" }}>
            Ledger Issues
          </span>
          <div className="metric-val" style={{ color: ledger.issues.length > 0 ? "var(--status-unresolved)" : "var(--status-clean)" }}>
            {ledger.issues.length}
          </div>
        </div>
        <div className="metric-card">
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600, textTransform: "uppercase" }}>
            Final Status
          </span>
          <div className="metric-val" style={{ fontSize: "1rem", color: result.status === "clean" ? "var(--status-clean)" : "var(--status-error)" }}>
            {result.status.toUpperCase()}
          </div>
        </div>
      </div>

      {/* Deterministic Bug Ledger */}
      <div className="glass-panel">
        <h3 className="section-title">
          <Terminal size={16} color="var(--accent-primary)" />
          <span>Static Bug Ledger (Pre-Execution Map)</span>
        </h3>
        
        {ledger.issues && ledger.issues.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", marginTop: "1rem" }}>
            {ledger.issues.map((issue, idx) => (
              <div
                key={idx}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "0.625rem 0.875rem",
                  borderRadius: 6,
                  backgroundColor: "var(--bg-primary)",
                  borderLeft: `3px solid ${
                    issue.severity === "error"
                      ? "var(--status-error)"
                      : issue.severity === "warning"
                      ? "var(--status-unresolved)"
                      : "var(--accent-primary)"
                  }`,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: "0.75rem",
                      color: "var(--text-muted)",
                      backgroundColor: "var(--bg-tertiary)",
                      padding: "0.125rem 0.375rem",
                      borderRadius: 4,
                    }}
                  >
                    Line {issue.line || "N/A"}
                  </span>
                  <span style={{ fontSize: "0.8125rem", color: "var(--text-primary)" }}>{issue.message}</span>
                </div>
                <span
                  className={`badge ${
                    issue.severity === "error"
                      ? "badge-danger"
                      : issue.severity === "warning"
                      ? "badge-warning"
                      : "badge-info"
                  }`}
                  style={{ fontSize: "0.6875rem" }}
                >
                  {issue.kind}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginTop: "0.5rem", display: "flex", alignItems: "center", gap: "0.375rem" }}>
            <CheckCircle size={14} color="var(--status-clean)" />
            No ledger issues detected. Code files parse cleanly without static alerts.
          </p>
        )}
      </div>

      {/* AST Structural Metadata */}
      <div className="glass-panel">
        <h3 className="section-title">
          <FileCode size={16} color="var(--accent-purple)" />
          <span>AST Structures Extracted</span>
        </h3>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1rem", marginTop: "1rem" }}>
          <div>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600 }}>Imports ({ledger.imports.length})</span>
            <div style={{ maxHeight: "100px", overflowY: "auto", marginTop: "0.25rem" }}>
              {ledger.imports.map((imp, idx) => (
                <div key={idx} style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", color: "var(--text-secondary)", padding: "0.125rem 0" }}>
                  {imp}
                </div>
              ))}
            </div>
          </div>
          <div>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600 }}>Functions ({ledger.functions.length})</span>
            <div style={{ maxHeight: "100px", overflowY: "auto", marginTop: "0.25rem" }}>
              {ledger.functions.map((f, idx) => (
                <div key={idx} style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", color: "var(--text-secondary)", padding: "0.125rem 0" }}>
                  {f.name} <span style={{ color: "var(--text-muted)" }}>@ line {f.line}</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600 }}>Classes ({ledger.classes.length})</span>
            <div style={{ maxHeight: "100px", overflowY: "auto", marginTop: "0.25rem" }}>
              {ledger.classes.map((c, idx) => (
                <div key={idx} style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", color: "var(--text-secondary)", padding: "0.125rem 0" }}>
                  {c.name} <span style={{ color: "var(--text-muted)" }}>@ line {c.line}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Attempts Execution Log */}
      <div>
        <h3 className="section-title" style={{ marginBottom: "0.75rem" }}>
          <List size={16} color="var(--accent-primary)" />
          <span>Agent Loop Attempts ({attempts.length})</span>
        </h3>
        
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {attempts.map((attempt, idx) => {
            const isOpen = openAttemptIdx === idx;
            const hasErrors = attempt.validation_errors.length > 0;
            return (
              <div key={idx} className="glass-panel" style={{ padding: 0, overflow: "hidden" }}>
                {/* Header Toggle */}
                <button
                  type="button"
                  style={{
                    width: "100%",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "1rem",
                    border: "none",
                    background: "var(--bg-secondary)",
                    cursor: "pointer",
                    textAlign: "left",
                  }}
                  onClick={() => setOpenAttemptIdx(isOpen ? null : idx)}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                    <span
                      style={{
                        width: "1.75rem",
                        height: "1.75rem",
                        borderRadius: "50%",
                        backgroundColor: hasErrors ? "var(--status-unresolved-glow)" : "var(--status-clean-glow)",
                        color: hasErrors ? "var(--status-unresolved)" : "var(--status-clean)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: "0.8125rem",
                        fontWeight: 700,
                      }}
                    >
                      {attempt.pass_number}
                    </span>
                    <div>
                      <h4 style={{ fontSize: "0.875rem", fontWeight: 700, color: "var(--text-primary)" }}>
                        {attempt.summary || `Pass ${attempt.pass_number}`}
                      </h4>
                      <p style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                        Applied: <strong>{attempt.applied_edits} edits</strong> · Failures:{" "}
                        <strong style={{ color: attempt.edit_failures.length > 0 ? "var(--status-error)" : "var(--text-muted)" }}>
                          {attempt.edit_failures.length}
                        </strong>
                      </p>
                    </div>
                  </div>
                  {isOpen ? <ChevronUp size={16} color="var(--text-secondary)" /> : <ChevronDown size={16} color="var(--text-secondary)" />}
                </button>

                {isOpen && (
                  <div style={{ padding: "1rem", borderTop: "1px solid var(--border-color)", backgroundColor: "rgba(0, 0, 0, 0.15)" }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "1rem" }}>
                      {/* Issues Targeted */}
                      {attempt.issues_found && attempt.issues_found.length > 0 && (
                        <div>
                          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600 }}>ISSUES DETECTED BY AGENT:</span>
                          <ul style={{ paddingLeft: "1.25rem", marginTop: "0.25rem" }}>
                            {attempt.issues_found.map((issue, i) => (
                              <li key={i} style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", padding: "0.125rem 0" }}>{issue}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Edit Failures */}
                      {attempt.edit_failures && attempt.edit_failures.length > 0 && (
                        <div style={{ padding: "0.5rem 0.75rem", borderRadius: 6, backgroundColor: "var(--status-error-glow)", border: "1px solid rgba(239, 68, 68, 0.2)" }}>
                          <span style={{ fontSize: "0.75rem", color: "var(--status-error)", fontWeight: 600, display: "flex", alignItems: "center", gap: "0.25rem" }}>
                            <Flame size={12} /> SPLICING REJECTION FINDINGS
                          </span>
                          <ul style={{ paddingLeft: "1.25rem", marginTop: "0.25rem" }}>
                            {attempt.edit_failures.map((err, i) => (
                              <li key={i} style={{ fontSize: "0.8125rem", color: "#fca5a5", padding: "0.125rem 0" }}>{err}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Validation Errors */}
                      {attempt.validation_errors && attempt.validation_errors.length > 0 ? (
                        <div style={{ padding: "0.5rem 0.75rem", borderRadius: 6, backgroundColor: "var(--status-error-glow)", border: "1px solid rgba(239, 68, 68, 0.2)" }}>
                          <span style={{ fontSize: "0.75rem", color: "var(--status-error)", fontWeight: 600, display: "flex", alignItems: "center", gap: "0.25rem" }}>
                            <AlertCircle size={12} /> VALIDATION GATE REJECTIONS
                          </span>
                          <ul style={{ paddingLeft: "1.25rem", marginTop: "0.25rem" }}>
                            {attempt.validation_errors.map((err, i) => (
                              <li key={i} style={{ fontSize: "0.8125rem", color: "#fca5a5", padding: "0.125rem 0", fontFamily: "var(--font-mono)" }}>{err}</li>
                            ))}
                          </ul>
                        </div>
                      ) : (
                        <div style={{ padding: "0.5rem 0.75rem", borderRadius: 6, backgroundColor: "var(--status-clean-glow)", border: "1px solid rgba(16, 185, 129, 0.2)" }}>
                          <span style={{ fontSize: "0.75rem", color: "var(--status-clean)", fontWeight: 600, display: "flex", alignItems: "center", gap: "0.25rem" }}>
                            <Shield size={12} /> PASSED ALL SANDBOX CONTRAINTS
                          </span>
                          <p style={{ fontSize: "0.8125rem", color: "#a7f3d0", marginTop: "0.125rem" }}>
                            Compiles, security scans clean, and executing sandbox returned zero errors.
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

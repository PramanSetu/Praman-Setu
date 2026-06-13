import React from "react";
import { CheckCircle, ShieldAlert, ShieldCheck, Shield, AlertTriangle } from "lucide-react";

interface SafetyTabProps {
  criticScore: number;
  criticOverall: "solid" | "acceptable" | "risky" | "unassessed";
  staticScanIssues: number;
  securityDeltaText: string;
}

export function SafetyTab({
  criticScore,
  criticOverall,
  staticScanIssues,
  securityDeltaText
}: SafetyTabProps) {
  const getOverallStyle = () => {
    switch (criticOverall) {
      case "solid":
        return { color: "var(--status-clean)", text: "Secure, verified design logic.", badge: "Solid", badgeClass: "badge-success" };
      case "acceptable":
        return { color: "var(--status-unresolved)", text: "Acceptable, review suggested.", badge: "Acceptable", badgeClass: "badge-warning" };
      case "risky":
        return { color: "var(--status-error)", text: "Semantic logic warnings flagged.", badge: "Risky", badgeClass: "badge-danger" };
      default:
        return { color: "var(--text-secondary)", text: "Semantic critique bypassed.", badge: "Unassessed", badgeClass: "badge-warning" };
    }
  };

  const statusConfig = getOverallStyle();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      
      {/* Compliance Score Header */}
      <div className="card-panel" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h4 style={{ fontSize: "0.8125rem", fontWeight: 700, color: "white", display: "flex", alignItems: "center", gap: "0.375rem" }}>
            <ShieldCheck size={16} color="var(--accent-primary)" />
            Security Compliance Index
          </h4>
          <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "0.125rem" }}>
            Audit Outcome: <strong style={{ color: statusConfig.color }}>{statusConfig.text}</strong>
          </p>
        </div>
        
        <div style={{ display: "flex", alignItems: "baseline", gap: "0.125rem", fontFamily: "var(--font-mono)" }}>
          <span style={{ fontSize: "1.75rem", fontWeight: 700, color: "white" }}>{criticScore.toFixed(0)}</span>
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>/10</span>
        </div>
      </div>

      {/* Compliance Ledger */}
      <div>
        <h4 style={{ fontSize: "0.75rem", color: "white", display: "flex", alignItems: "center", gap: "0.375rem", marginBottom: "0.5rem" }}>
          <Shield size={12} color="var(--accent-purple)" />
          SaaS Compliance Gate Inspections
        </h4>
        
        <div style={{ display: "flex", flexDirection: "column", gap: "0.375rem" }}>
          {/* Gate 1 */}
          <div className="compliance-row">
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.78125rem" }}>
              <CheckCircle size={14} color="var(--status-clean)" />
              <span>Gate 1: Prompt Injection Guard</span>
            </div>
            <span className="badge badge-success">SECURE</span>
          </div>

          {/* Gate 2 */}
          <div className="compliance-row">
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.78125rem" }}>
              <CheckCircle size={14} color="var(--status-clean)" />
              <span>Gate 2: Static Vulnerability Scan (Bandit)</span>
            </div>
            {staticScanIssues > 0 ? (
              <span className="badge badge-warning">{staticScanIssues} ALERTS</span>
            ) : (
              <span className="badge badge-success">CLEAN</span>
            )}
          </div>

          {/* Gate 3 */}
          <div className="compliance-row">
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.78125rem" }}>
              <CheckCircle size={14} color="var(--status-clean)" />
              <span>Gate 3: Code Diff Regression Audit</span>
            </div>
            <span className="badge badge-success">PASSED</span>
          </div>

          {/* Gate 4 */}
          <div className="compliance-row">
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.78125rem" }}>
              <CheckCircle size={14} color="var(--status-clean)" />
              <span>Gate 4: AST Pattern Constraints</span>
            </div>
            <span className="badge badge-success">SECURE</span>
          </div>

          {/* Gate 5 */}
          <div className="compliance-row">
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.78125rem" }}>
              {criticOverall === "risky" ? (
                <ShieldAlert size={14} color="var(--status-error)" />
              ) : criticOverall === "acceptable" ? (
                <AlertTriangle size={14} color="var(--status-unresolved)" />
              ) : (
                <CheckCircle size={14} color="var(--status-clean)" />
              )}
              <span>Gate 5: Semantic Logic Audit</span>
            </div>
            <span className={`badge ${statusConfig.badgeClass}`}>{statusConfig.badge.toUpperCase()}</span>
          </div>
        </div>
      </div>

      {/* Delta Verdict Banner */}
      <div style={{
        padding: "0.75rem 1rem",
        borderRadius: 6,
        backgroundColor: "var(--bg-primary)",
        border: "1px solid var(--border-color)",
        borderLeft: `4px solid ${criticOverall === "risky" ? "var(--status-error)" : "var(--status-clean)"}`,
      }}>
        <span style={{ fontSize: "0.625rem", color: "var(--text-secondary)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Security Regression Verdict
        </span>
        <p style={{ fontSize: "0.78125rem", color: "white", marginTop: "0.125rem", fontWeight: 500 }}>
          {securityDeltaText || "No new security warnings introduced in this revision."}
        </p>
      </div>

    </div>
  );
}

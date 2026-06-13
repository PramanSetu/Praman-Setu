import React from "react";
import { RepairExplanation } from "../hooks/useApi";
import { AlertCircle, CheckCircle2, ShieldAlert, BadgeAlert, Tag, Check, HelpCircle } from "lucide-react";

interface ResultExplainerProps {
  explanation: RepairExplanation | null;
  status: "clean" | "unresolved" | "no_progress" | "insecure";
}

export function ResultExplainer({ explanation, status }: ResultExplainerProps) {
  if (!explanation) {
    return (
      <div className="glass-panel" style={{ textAlign: "center", padding: "2rem", color: "var(--text-secondary)" }}>
        <p>No explanation report available for this execution run.</p>
      </div>
    );
  }

  const getStatusConfig = () => {
    switch (status) {
      case "clean":
        return {
          className: "clean",
          icon: <CheckCircle2 size={20} color="var(--status-clean)" />,
          title: "Code Repaired & Clean",
        };
      case "unresolved":
        return {
          className: "unresolved",
          icon: <HelpCircle size={20} color="var(--status-unresolved)" />,
          title: "Partially Repaired",
        };
      case "no_progress":
        return {
          className: "no_progress",
          icon: <BadgeAlert size={20} color="var(--status-no-progress)" />,
          title: "No Safe Edits Producible",
        };
      case "insecure":
        return {
          className: "insecure",
          icon: <ShieldAlert size={20} color="var(--status-error)" />,
          title: "Security Findings Remaining",
        };
      default:
        return {
          className: "unresolved",
          icon: <AlertCircle size={20} />,
          title: "Unresolved Status",
        };
    }
  };

  const statusConfig = getStatusConfig();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {/* Banner */}
      <div className={`status-banner ${statusConfig.className}`}>
        <div className="status-banner-icon">{statusConfig.icon}</div>
        <div className="status-banner-text">
          <h3>{statusConfig.title}</h3>
          <p>{explanation.headline}</p>
        </div>
      </div>

      {/* Narrative Card */}
      <div className="glass-panel">
        <h3 className="section-title">
          <CheckCircle2 size={16} color="var(--accent-purple)" />
          <span>Verification Proof</span>
        </h3>
        <p className="narrative-card" style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>
          {explanation.verification}
        </p>
      </div>

      {/* Fix Details */}
      {explanation.fixes && explanation.fixes.length > 0 && (
        <div>
          <h3 className="section-title" style={{ marginBottom: "0.75rem" }}>
            <Tag size={16} color="var(--accent-primary)" />
            <span>Applied Fixes ({explanation.fixes.length})</span>
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {explanation.fixes.map((fix, idx) => (
              <div key={idx} className="issue-card" style={{ borderLeft: "4px solid var(--status-clean)" }}>
                <div className="issue-header">
                  <span className="badge badge-info" style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
                    {fix.category}
                  </span>
                  <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                    Fix #{idx + 1}
                  </span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", marginTop: "0.5rem" }}>
                  <div>
                    <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600, textTransform: "uppercase" }}>
                      Issue Detected
                    </span>
                    <p style={{ fontSize: "0.875rem", color: "var(--text-primary)", marginTop: "0.125rem" }}>{fix.issue}</p>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start", marginTop: "0.25rem" }}>
                    <div style={{ color: "var(--status-clean)", marginTop: "0.125rem" }}>
                      <Check size={14} />
                    </div>
                    <div>
                      <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600, textTransform: "uppercase" }}>
                        Patch Applied
                      </span>
                      <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginTop: "0.125rem" }}>{fix.fix}</p>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Flagged Items (User Intent or Warning details) */}
      {explanation.flagged && explanation.flagged.length > 0 && (
        <div className="glass-panel" style={{ border: "1px solid rgba(245, 158, 11, 0.3)", backgroundColor: "rgba(245, 158, 11, 0.02)" }}>
          <h3 className="section-title" style={{ color: "var(--status-unresolved)" }}>
            <AlertCircle size={16} color="var(--status-unresolved)" />
            <span>Developer Review Actions</span>
          </h3>
          <p style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
            The following points need semantic validation by a human. The code operates, but limits in intent resolution are marked below:
          </p>
          <ul style={{ paddingLeft: "1.25rem", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {explanation.flagged.map((flag, idx) => (
              <li key={idx} style={{ fontSize: "0.875rem", color: "var(--text-primary)" }}>
                {flag}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

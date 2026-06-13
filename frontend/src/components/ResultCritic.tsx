import React from "react";
import { CritiqueReport } from "../hooks/useApi";
import { Eye, ShieldAlert, Sparkles, AlertOctagon, HelpCircle, Check, X, ShieldCheck } from "lucide-react";

interface ResultCriticProps {
  critique: CritiqueReport | null;
}

export function ResultCritic({ critique }: ResultCriticProps) {
  if (!critique) {
    return (
      <div className="glass-panel" style={{ textAlign: "center", padding: "2rem", color: "var(--text-secondary)" }}>
        <p>Critic Audit report is disabled or unavailable for this run.</p>
      </div>
    );
  }

  const getScoreBox = () => {
    switch (critique.overall) {
      case "solid":
        return {
          class: "solid",
          text: "Solid Fix",
          color: "var(--status-clean)",
          icon: <ShieldCheck size={20} color="var(--status-clean)" />,
        };
      case "acceptable":
        return {
          class: "acceptable",
          text: "Acceptable",
          color: "var(--status-unresolved)",
          icon: <HelpCircle size={20} color="var(--status-unresolved)" />,
        };
      case "risky":
        return {
          class: "risky",
          text: "Risky",
          color: "var(--status-error)",
          icon: <AlertOctagon size={20} color="var(--status-error)" />,
        };
      default:
        return {
          class: "",
          text: "Unassessed",
          color: "var(--text-secondary)",
          icon: <Eye size={20} color="var(--text-secondary)" />,
        };
    }
  };

  const scoreBox = getScoreBox();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {/* Score and Overview */}
      <div className="glass-panel">
        <div className="critic-score-row">
          <div>
            <h3 style={{ fontSize: "1.125rem", fontWeight: 700, display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <Sparkles size={16} color="var(--accent-purple)" />
              Critic Semantic Audit
            </h3>
            <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginTop: "0.5rem" }}>
              {critique.summary}
            </p>
          </div>
          <div className={`critic-score-box ${scoreBox.class}`} style={{ flexShrink: 0 }}>
            <div style={{ display: "flex", justifyContent: "center", marginBottom: "0.25rem" }}>
              {scoreBox.icon}
            </div>
            <span style={{ fontSize: "0.8125rem", fontWeight: 700, color: scoreBox.color }}>
              {scoreBox.text}
            </span>
          </div>
        </div>
      </div>

      {/* Human Review Ledger Checklist */}
      {critique.needs_human_review && critique.needs_human_review.length > 0 && (
        <div>
          <h3 className="section-title">
            <ShieldAlert size={16} color="var(--status-error)" />
            <span>Authoritative Human Review List ({critique.needs_human_review.length})</span>
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {critique.needs_human_review.map((item, idx) => (
              <div key={idx} className="action-item">
                <input
                  type="checkbox"
                  id={`review-${idx}`}
                  style={{
                    marginTop: "0.25rem",
                    accentColor: "var(--accent-primary)",
                    cursor: "pointer",
                  }}
                />
                <label
                  htmlFor={`review-${idx}`}
                  style={{
                    fontSize: "0.875rem",
                    color: "var(--text-primary)",
                    cursor: "pointer",
                    userSelect: "none",
                  }}
                >
                  {item}
                </label>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Fix Assessments */}
      {critique.assessments && critique.assessments.length > 0 && (
        <div>
          <h3 className="section-title">
            <Eye size={16} color="var(--accent-primary)" />
            <span>Fix Code Assessments</span>
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {critique.assessments.map((assessment, idx) => (
              <div key={idx} className="issue-card">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.875rem", fontWeight: 600, color: "var(--accent-purple)" }}>
                    {assessment.target}
                  </span>
                  <span className={`badge ${assessment.confidence === "high" ? "badge-info" : assessment.confidence === "medium" ? "badge-warning" : "badge-danger"}`}>
                    {assessment.confidence} Confidence
                  </span>
                </div>
                
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", margin: "0.5rem 0" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "0.8125rem" }}>
                    {assessment.addresses_root_cause ? (
                      <Check size={14} color="var(--status-clean)" />
                    ) : (
                      <X size={14} color="var(--status-error)" />
                    )}
                    <span style={{ color: assessment.addresses_root_cause ? "var(--text-primary)" : "var(--status-unresolved)" }}>
                      Addresses Root Cause
                    </span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "0.8125rem" }}>
                    {assessment.preserves_intent ? (
                      <Check size={14} color="var(--status-clean)" />
                    ) : (
                      <X size={14} color="var(--status-error)" />
                    )}
                    <span style={{ color: assessment.preserves_intent ? "var(--text-primary)" : "var(--status-unresolved)" }}>
                      Preserves Intent
                    </span>
                  </div>
                </div>

                {assessment.concern && (
                  <div style={{ marginTop: "0.5rem", padding: "0.5rem 0.75rem", borderRadius: 4, backgroundColor: "var(--bg-primary)", borderLeft: "2px solid var(--status-unresolved)" }}>
                    <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600 }}>CONCERNED:</span>
                    <p style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", marginTop: "0.125rem" }}>
                      {assessment.concern}
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Latent Logic Audit */}
      {critique.logic_audit && critique.logic_audit.length > 0 && (
        <div>
          <h3 className="section-title">
            <ShieldAlert size={16} color="var(--status-unresolved)" />
            <span>Latent Logic Audit (Whole-File Inspection)</span>
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {critique.logic_audit.map((audit, idx) => (
              <div key={idx} className="issue-card" style={{ borderLeft: `4px solid ${audit.severity === "high" ? "var(--status-error)" : audit.severity === "medium" ? "var(--status-unresolved)" : "var(--accent-primary)"}` }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
                    Location: <strong>{audit.location}</strong>
                  </span>
                  <span className={`badge ${audit.severity === "high" ? "badge-danger" : audit.severity === "medium" ? "badge-warning" : "badge-info"}`}>
                    {audit.severity} Severity
                  </span>
                </div>
                <p style={{ fontSize: "0.875rem", color: "var(--text-primary)", marginTop: "0.5rem" }}>
                  {audit.issue}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

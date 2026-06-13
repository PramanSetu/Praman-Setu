import React from "react";
import { Sparkles, BrainCircuit, Activity, Link2, AlertTriangle, CheckCircle } from "lucide-react";

interface HypothesisInfo {
  id: string;
  theory: string;
  confidence: number;
  fix_direction: string;
  risk_if_wrong: string;
}

interface ReasoningTabProps {
  rootCause: string;
  hypothesis: HypothesisInfo | null;
  reasoningTrace: string;
  semanticDiff: string;
  downstreamImpacts: string[];
}

export function ReasoningTab({
  rootCause,
  hypothesis,
  reasoningTrace,
  semanticDiff,
  downstreamImpacts
}: ReasoningTabProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      
      {/* Root Cause Banner Card */}
      <div style={{
        padding: "0.75rem 1rem",
        borderRadius: 6,
        backgroundColor: "var(--accent-primary-glow)",
        border: "1px solid rgba(37, 99, 235, 0.15)",
        borderLeft: "4px solid var(--accent-primary)",
        display: "flex",
        alignItems: "flex-start",
        gap: "0.75rem"
      }}>
        <BrainCircuit size={16} color="var(--accent-primary)" style={{ marginTop: "0.125rem", flexShrink: 0 }} />
        <div>
          <span style={{ fontSize: "0.625rem", color: "var(--accent-primary)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Root Cause Diagnosis
          </span>
          <p style={{ fontSize: "0.8125rem", fontWeight: 600, color: "white", marginTop: "0.125rem" }}>
            {rootCause || "Analyzing structural root cause…"}
          </p>
        </div>
      </div>

      {/* Main Grid: Hypothesis & Semantic Diff */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "1rem" }} className="lg-grid-cols-2">
        
        {/* Hypothesis Box */}
        {hypothesis && (
          <div className="card-panel" style={{ display: "flex", flexDirection: "column", justifyContext: "space-between", gap: "0.5rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h4 style={{ fontSize: "0.75rem", color: "white", display: "flex", alignItems: "center", gap: "0.375rem" }}>
                <BrainCircuit size={12} color="var(--accent-purple)" />
                Hypothesis: {hypothesis.id}
              </h4>
              <span style={{ fontSize: "0.6875rem", color: "var(--text-secondary)" }}>
                Direction: <strong>{hypothesis.fix_direction}</strong>
              </span>
            </div>

            <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", lineHeight: 1.4 }}>
              {hypothesis.theory}
            </p>

            <div style={{ borderTop: "1px solid var(--border-color)", paddingTop: "0.5rem", marginTop: "auto" }}>
              <span style={{ fontSize: "0.6875rem", color: "var(--text-muted)", display: "block", marginBottom: "0.25rem" }}>
                CRITICAL CONFIDENCE INDEX
              </span>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <div style={{ flex: 1, height: "6px", backgroundColor: "var(--border-color)", borderRadius: "3px", overflow: "hidden" }}>
                  <div style={{
                    width: `${(hypothesis.confidence * 100).toFixed(0)}%`,
                    height: "100%",
                    backgroundColor: "var(--accent-purple)",
                    borderRadius: "3px"
                  }} />
                </div>
                <span style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--accent-purple)", fontFamily: "var(--font-mono)" }}>
                  {(hypothesis.confidence * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Semantic Diff Box */}
        <div className="card-panel" style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <h4 style={{ fontSize: "0.75rem", color: "white", display: "flex", alignItems: "center", gap: "0.375rem" }}>
            <Activity size={12} color="var(--status-clean)" />
            Behavior Corrections
          </h4>
          <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", lineHeight: 1.4, flex: 1 }}>
            {semanticDiff || "No behavior adjustments declared."}
          </p>
          {hypothesis?.risk_if_wrong && (
            <div style={{
              marginTop: "auto",
              padding: "0.375rem 0.5rem",
              borderRadius: 4,
              backgroundColor: "rgba(234, 179, 8, 0.03)",
              border: "1px solid rgba(234, 179, 8, 0.1)",
              fontSize: "0.6875rem",
              color: "var(--status-unresolved)",
              display: "flex",
              alignItems: "center",
              gap: "0.25rem"
            }}>
              <AlertTriangle size={10} />
              <span>Risk: {hypothesis.risk_if_wrong}</span>
            </div>
          )}
        </div>
      </div>

      {/* Streamed Reasoning Log block */}
      <div style={{ display: "flex", flexDirection: "column", gap: "0.375rem" }}>
        <h4 style={{ fontSize: "0.75rem", color: "white", display: "flex", alignItems: "center", gap: "0.375rem" }}>
          <Sparkles size={12} color="var(--accent-primary)" />
          Agent Reasoning Execution Trace
        </h4>
        <pre style={{
          backgroundColor: "var(--bg-primary)",
          border: "1px solid var(--border-color)",
          borderRadius: 6,
          padding: "0.75rem",
          minHeight: "120px",
          maxHeight: "220px",
          overflowY: "auto",
          fontFamily: "var(--font-mono)",
          fontSize: "0.75rem",
          lineHeight: 1.6,
          color: "var(--text-secondary)",
          whiteSpace: "pre-wrap"
        }}>
          {reasoningTrace || <span style={{ color: "var(--text-muted)", className: "pulse" }}>Generating agent narration…</span>}
        </pre>
      </div>

      {/* Downstream Impact Audits */}
      <div style={{ display: "flex", flexDirection: "column", gap: "0.375rem" }}>
        <h4 style={{ fontSize: "0.75rem", color: "white", display: "flex", alignItems: "center", gap: "0.375rem" }}>
          <Link2 size={12} color="var(--status-unresolved)" />
          Downstream Impact Audit
        </h4>
        {downstreamImpacts && downstreamImpacts.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.375rem" }}>
            {downstreamImpacts.map((impact, idx) => (
              <div key={idx} style={{
                padding: "0.5rem 0.75rem",
                borderRadius: 6,
                backgroundColor: "var(--bg-primary)",
                border: "1px solid var(--border-color)",
                borderLeft: "3px solid var(--status-unresolved)",
                fontSize: "0.75rem",
                color: "var(--text-secondary)",
                display: "flex",
                alignItems: "center",
                gap: "0.5rem"
              }}>
                <AlertTriangle size={12} color="var(--status-unresolved)" style={{ flexShrink: 0 }} />
                <span>{impact}</span>
              </div>
            ))}
          </div>
        ) : (
          <div style={{
            padding: "0.5rem 0.75rem",
            borderRadius: 6,
            backgroundColor: "var(--bg-primary)",
            border: "1px solid var(--border-color)",
            borderLeft: "3px solid var(--status-clean)",
            fontSize: "0.75rem",
            color: "var(--text-secondary)",
            display: "flex",
            alignItems: "center",
            gap: "0.5rem"
          }}>
            <CheckCircle size={12} color="var(--status-clean)" />
            <span>Downstream Verification: Safe. No external regressions or API breaking changes detected.</span>
          </div>
        )}
      </div>

      <style>{`
        .lg-grid-cols-2 {
          grid-template-columns: 1fr;
        }
        @media (min-width: 768px) {
          .lg-grid-cols-2 {
            grid-template-columns: 1fr 1fr;
          }
        }
      `}</style>
    </div>
  );
}

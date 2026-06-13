import React, { useState } from "react";
import { AnalyzeResponse } from "../hooks/useApi";
import { Activity, Clock, Cpu, FileCode, CheckCircle, XCircle, AlertTriangle, Layers } from "lucide-react";

interface TraceViewerProps {
  response: AnalyzeResponse | null;
}

export function TraceViewer({ response }: TraceViewerProps) {
  const [activeTab, setActiveTab] = useState<"diagnoser" | "patcher" | "validator" | "performance">("diagnoser");

  if (!response) {
    return (
      <div className="glass-panel" style={{ textAlign: "center", padding: "2rem", color: "var(--text-secondary)" }}>
        <p>No agent pipeline trace data available. Run "Analyze in Agent Graph" to construct this pipeline map.</p>
      </div>
    );
  }

  const { diagnoser_output, patcher_output, validator_report, trace } = response;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      
      {/* Run Summary Bar */}
      <div className="glass-panel" style={{ padding: "1rem 1.5rem" }}>
        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: "1rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <Activity size={18} color="var(--accent-primary)" />
            <span style={{ fontSize: "0.875rem" }}>
              Graph Execution status: <strong style={{ color: response.status === "execution_clean" || response.status === "ready" ? "var(--status-clean)" : "var(--status-error)" }}>
                {response.status.toUpperCase()}
              </strong>
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "1.5rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
              <Clock size={14} />
              <span>Duration: <strong>{trace?.total_ms ? `${(trace.total_ms / 1000).toFixed(2)}s` : "N/A"}</strong></span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
              <Cpu size={14} />
              <span>Retries: <strong>{response.retry_count}</strong></span>
            </div>
            {response.human_review_flag && (
              <span className="badge badge-warning" style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
                <AlertTriangle size={12} /> Needs Review
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Main Content Tabs */}
      <div className="tabs-container" style={{ marginBottom: "1rem" }}>
        <button
          type="button"
          className={`tab-btn ${activeTab === "diagnoser" ? "active" : ""}`}
          onClick={() => setActiveTab("diagnoser")}
        >
          <Layers size={14} />
          1. Diagnoser
        </button>
        <button
          type="button"
          className={`tab-btn ${activeTab === "patcher" ? "active" : ""}`}
          onClick={() => setActiveTab("patcher")}
          disabled={!patcher_output}
        >
          <FileCode size={14} />
          2. Patcher
        </button>
        <button
          type="button"
          className={`tab-btn ${activeTab === "validator" ? "active" : ""}`}
          onClick={() => setActiveTab("validator")}
          disabled={!validator_report}
        >
          <CheckCircle size={14} />
          3. Validator
        </button>
        <button
          type="button"
          className={`tab-btn ${activeTab === "performance" ? "active" : ""}`}
          onClick={() => setActiveTab("performance")}
        >
          <Clock size={14} />
          Telemetry Metrics
        </button>
      </div>

      {/* Tab Panels */}
      <div className="glass-panel" style={{ minHeight: "350px" }}>
        {activeTab === "diagnoser" && (
          <div>
            {diagnoser_output ? (
              <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
                <div>
                  <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600 }}>ROOT CAUSE IDENTIFIED:</span>
                  <p style={{ fontSize: "0.9375rem", color: "var(--text-primary)", marginTop: "0.25rem", lineHeight: 1.5 }}>
                    {diagnoser_output.root_cause}
                  </p>
                  <span className="badge badge-info" style={{ marginTop: "0.5rem" }}>
                    Scope: {diagnoser_output.affected_scope}
                  </span>
                </div>

                {/* Hypotheses List */}
                <div>
                  <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600 }}>AGENT HYPOTHESES AUDIT:</span>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "0.75rem", marginTop: "0.5rem" }}>
                    {diagnoser_output.hypotheses.map((h, i) => (
                      <div
                        key={i}
                        className="issue-card"
                        style={{
                          borderLeft: h.id === response.hypothesis_used ? "4px solid var(--accent-primary)" : "1px solid var(--border-color)",
                          backgroundColor: h.id === response.hypothesis_used ? "var(--accent-primary-glow)" : "rgba(255, 255, 255, 0.01)"
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <span style={{ fontWeight: 700, fontSize: "0.875rem", color: "var(--text-primary)" }}>
                            {h.id}: {h.theory.split("—")[0]}
                          </span>
                          <span className={`badge ${h.confidence >= 0.7 ? "badge-info" : "badge-warning"}`}>
                            {(h.confidence * 100).toFixed(0)}% confidence
                          </span>
                        </div>
                        <p style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", marginTop: "0.375rem" }}>
                          {h.theory}
                        </p>
                        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.5rem" }}>
                          Direction: <code style={{ color: "var(--text-primary)" }}>{h.fix_direction}</code>
                        </div>
                        {h.risk_if_wrong && (
                          <div style={{ fontSize: "0.75rem", color: "var(--status-unresolved)", marginTop: "0.25rem" }}>
                            Risk if wrong: {h.risk_if_wrong}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Generated Test assertions */}
                {diagnoser_output.generated_test && (
                  <div>
                    <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600 }}>SYNTHETIC REPAIR VALIDATION TEST:</span>
                    <pre className="code-pre" style={{ backgroundColor: "var(--bg-primary)", borderRadius: 6, marginTop: "0.375rem", maxHeight: "150px", overflowY: "auto" }}>
                      <code>{diagnoser_output.generated_test}</code>
                    </pre>
                  </div>
                )}
              </div>
            ) : (
              <p style={{ color: "var(--text-secondary)" }}>No diagnoser data generated. The graph may have skipped this step on hot-path checks.</p>
            )}
          </div>
        )}

        {activeTab === "patcher" && patcher_output && (
          <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
            <div>
              <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600 }}>PATCH APPROACH:</span>
              <p style={{ fontSize: "0.875rem", color: "var(--text-primary)", marginTop: "0.25rem" }}>
                {patcher_output.approach}
              </p>
              <div style={{ display: "flex", gap: "1rem", marginTop: "0.5rem" }}>
                <span className="badge badge-info">Target: {patcher_output.patch_target}</span>
                <span className="badge badge-info">Hypothesis: {patcher_output.hypothesis_used}</span>
                <span className="badge badge-info">Changed: {patcher_output.lines_changed} lines</span>
              </div>
            </div>

            {/* Diff content */}
            {patcher_output.unified_diff && (
              <div>
                <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600 }}>UNIFIED DIFF PROPOSED:</span>
                <pre className="code-pre" style={{ backgroundColor: "var(--bg-primary)", borderRadius: 6, marginTop: "0.375rem", overflowX: "auto" }}>
                  <code>{patcher_output.unified_diff}</code>
                </pre>
              </div>
            )}
          </div>
        )}

        {activeTab === "validator" && validator_report && (
          <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              {validator_report.overall_passed ? (
                <CheckCircle size={18} color="var(--status-clean)" />
              ) : (
                <XCircle size={18} color="var(--status-error)" />
              )}
              <span style={{ fontSize: "0.9375rem", fontWeight: 700 }}>
                {validator_report.overall_passed ? "Validation Gate Passed" : "Validation Gate Rejected"}
              </span>
            </div>
            
            <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)" }}>
              {validator_report.summary}
            </p>

            {/* Detailed Gate Results */}
            <div>
              <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600 }}>GATE telemetry DETAILS:</span>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", marginTop: "0.5rem" }}>
                {Object.entries(validator_report.gate_results).map(([gate, info], idx) => (
                  <div
                    key={idx}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "0.5rem 0.75rem",
                      borderRadius: 6,
                      backgroundColor: "var(--bg-primary)",
                      border: "1px solid var(--border-color)",
                    }}
                  >
                    <span style={{ fontSize: "0.8125rem", fontWeight: 600, textTransform: "capitalize" }}>{gate}</span>
                    <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
                      <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>{info.duration_s.toFixed(2)}s</span>
                      {info.passed ? (
                        <span style={{ color: "var(--status-clean)", display: "flex", alignItems: "center", gap: "0.25rem", fontSize: "0.75rem", fontWeight: 600 }}>
                          <CheckCircle size={12} /> Passed
                        </span>
                      ) : (
                        <span style={{ color: "var(--status-error)", display: "flex", alignItems: "center", gap: "0.25rem", fontSize: "0.75rem", fontWeight: 600 }}>
                          <XCircle size={12} /> Failed
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Failures */}
            {validator_report.detailed_failures && validator_report.detailed_failures.length > 0 && (
              <div>
                <span style={{ fontSize: "0.75rem", color: "var(--status-error)", fontWeight: 600 }}>GATE CRASH ERRORS:</span>
                <pre className="code-pre" style={{ backgroundColor: "var(--status-error-glow)", border: "1px solid rgba(239, 68, 68, 0.15)", borderRadius: 6, color: "#fca5a5", marginTop: "0.375rem" }}>
                  <code>{validator_report.detailed_failures.join("\n")}</code>
                </pre>
              </div>
            )}
          </div>
        )}

        {activeTab === "performance" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
            <div>
              <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600 }}>AGENT NODE EXECUTION TIMELINE:</span>
              {trace?.nodes && trace.nodes.length > 0 ? (
                <div className="trace-timeline" style={{ marginTop: "1rem" }}>
                  {trace.nodes.map((node, i) => (
                    <div key={i} className="trace-node success">
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontSize: "0.875rem", fontWeight: 600, color: "var(--text-primary)", textTransform: "capitalize" }}>
                          {node.name} Node
                        </span>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
                          {node.duration_ms.toFixed(0)} ms
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", marginTop: "0.5rem" }}>Timeline metadata unavailable.</p>
              )}
            </div>

            {/* LLM Costs */}
            {trace?.llm_calls && trace.llm_calls.length > 0 && (
              <div>
                <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 600 }}>LLM COMPLETIONS telemetry:</span>
                <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", marginTop: "0.5rem" }}>
                  {trace.llm_calls.map((call, i) => (
                    <div
                      key={i}
                      style={{
                        padding: "0.5rem 0.75rem",
                        borderRadius: 6,
                        backgroundColor: "var(--bg-primary)",
                        border: "1px solid var(--border-color)",
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                      }}
                    >
                      <div>
                        <span style={{ fontSize: "0.8125rem", fontWeight: 600, color: "var(--accent-purple)" }}>{call.model}</span>
                        <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.125rem" }}>
                          Prompt: {call.prompt_tokens} t · Completion: {call.completion_tokens} t
                        </p>
                      </div>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
                        {call.latency_ms} ms
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

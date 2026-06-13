import React, { useState } from "react";
import { useApi } from "./hooks/useApi";
import { Header } from "./components/Header";
import { CodeInput } from "./components/CodeInput";
import { DiffViewer } from "./components/DiffViewer";
import { ResultExplainer } from "./components/ResultExplainer";
import { ResultCritic } from "./components/ResultCritic";
import { SandboxReport } from "./components/SandboxReport";
import { TraceViewer } from "./components/TraceViewer";
import { ArrowLeft, ShieldCheck, Flame, Cpu, Terminal, Award, HelpCircle } from "lucide-react";

export function App() {
  const {
    health,
    healthStatus,
    loading,
    error,
    repairResult,
    analyzeResult,
    mode,
    runRepair,
    runAnalyze,
    checkHealth,
    clearResults,
  } = useApi();

  const [activeTab, setActiveTab] = useState<"narrative" | "critic" | "sandbox" | "trace">("narrative");

  // Keep track of the inputs last run, so we can display them in the diff/telemetry
  const [lastInput, setLastInput] = useState<{
    code: string;
    filename: string | null;
    errorMsg: string | null;
  }>({ code: "", filename: null, errorMsg: null });

  const handleRepairSubmit = (
    code: string,
    filename: string | null,
    errorMsg: string | null,
    maxPasses: number,
    explain: boolean,
    critique: boolean
  ) => {
    setLastInput({ code, filename, errorMsg });
    runRepair(code, filename, errorMsg, maxPasses, explain, critique);
    setActiveTab("narrative");
  };

  const handleAnalyzeSubmit = (code: string, filename: string | null, errorMsg: string | null) => {
    setLastInput({ code, filename, errorMsg });
    runAnalyze(code, filename, errorMsg);
    setActiveTab("trace");
  };

  const isShowingResults = repairResult || analyzeResult;

  return (
    <div className="app-container">
      <Header health={health} healthStatus={healthStatus} onRefreshHealth={checkHealth} />

      <main className="main-content">
        {error && (
          <div
            className="glass-panel"
            style={{
              borderColor: "rgba(239, 68, 68, 0.3)",
              backgroundColor: "var(--status-error-glow)",
              color: "var(--status-error)",
              padding: "1rem",
              marginBottom: "1.5rem",
              borderRadius: 8,
              fontSize: "0.875rem",
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
            }}
          >
            <Flame size={16} />
            <span>
              <strong>Execution Error:</strong> {error}
            </span>
          </div>
        )}

        {!isShowingResults ? (
          /* Editor / Entry Page */
          <div className="editor-container">
            <div>
              <CodeInput
                loading={loading}
                onRepair={handleRepairSubmit}
                onAnalyze={handleAnalyzeSubmit}
              />
            </div>

            {/* Intro / Documentation Panel */}
            <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
              <div className="glass-panel">
                <h3 className="section-title">
                  <Award size={18} color="var(--accent-purple)" />
                  <span>Welcome to Praman Setu</span>
                </h3>
                <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", lineHeight: 1.6 }}>
                  Praman Setu bridges sandbox execution verification with semantic agent guardrails. Paste your code and any terminal crash traceback to diagnose and repair errors instantly.
                </p>
              </div>

              <div className="glass-panel">
                <h3 className="section-title" style={{ fontSize: "0.9375rem" }}>
                  <Cpu size={16} color="var(--accent-primary)" />
                  <span>How it works</span>
                </h3>
                <div style={{ display: "flex", flexDirection: "column", gap: "1rem", marginTop: "0.5rem" }}>
                  <div style={{ display: "flex", gap: "0.75rem" }}>
                    <div style={{
                      width: "1.5rem", height: "1.5rem", borderRadius: "50%",
                      backgroundColor: "var(--bg-tertiary)", color: "var(--text-primary)",
                      display: "flex", alignItems: "center", justifyContext: "center",
                      fontSize: "0.75rem", fontWeight: 700, flexShrink: 0, paddingLeft: "0.5rem", paddingTop: "0.1rem"
                    }}>1</div>
                    <div>
                      <h4 style={{ fontSize: "0.8125rem", fontWeight: 700 }}>Smart Input Parser</h4>
                      <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "0.125rem" }}>
                        Analyzes files, identifies language extension/shebang, and flags scripting inputs.
                      </p>
                    </div>
                  </div>

                  <div style={{ display: "flex", gap: "0.75rem" }}>
                    <div style={{
                      width: "1.5rem", height: "1.5rem", borderRadius: "50%",
                      backgroundColor: "var(--bg-tertiary)", color: "var(--text-primary)",
                      display: "flex", alignItems: "center", justifyContext: "center",
                      fontSize: "0.75rem", fontWeight: 700, flexShrink: 0, paddingLeft: "0.5rem", paddingTop: "0.1rem"
                    }}>2</div>
                    <div>
                      <h4 style={{ fontSize: "0.8125rem", fontWeight: 700 }}>Deterministic Bug Ledger</h4>
                      <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "0.125rem" }}>
                        Scans code structure locally to map undefined symbols, missing imports, and compilation limits.
                      </p>
                    </div>
                  </div>

                  <div style={{ display: "flex", gap: "0.75rem" }}>
                    <div style={{
                      width: "1.5rem", height: "1.5rem", borderRadius: "50%",
                      backgroundColor: "var(--bg-tertiary)", color: "var(--text-primary)",
                      display: "flex", alignItems: "center", justifyContext: "center",
                      fontSize: "0.75rem", fontWeight: 700, flexShrink: 0, paddingLeft: "0.5rem", paddingTop: "0.1rem"
                    }}>3</div>
                    <div>
                      <h4 style={{ fontSize: "0.8125rem", fontWeight: 700 }}>Hardened Sandbox Validation</h4>
                      <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "0.125rem" }}>
                        Runs modified source inside isolated container pools checking runtime syntax, tests, and security.
                      </p>
                    </div>
                  </div>

                  <div style={{ display: "flex", gap: "0.75rem" }}>
                    <div style={{
                      width: "1.5rem", height: "1.5rem", borderRadius: "50%",
                      backgroundColor: "var(--bg-tertiary)", color: "var(--text-primary)",
                      display: "flex", alignItems: "center", justifyContext: "center",
                      fontSize: "0.75rem", fontWeight: 700, flexShrink: 0, paddingLeft: "0.5rem", paddingTop: "0.1rem"
                    }}>4</div>
                    <div>
                      <h4 style={{ fontSize: "0.8125rem", fontWeight: 700 }}>Critic Semantic Guardrails</h4>
                      <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "0.125rem" }}>
                        Audits full files for latent logic bugs, symptom masking, and provides a list of review actions.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* Dashboard Results Page */
          <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
            
            {/* Header controls for dashboard */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <button type="button" className="btn btn-secondary" onClick={clearResults}>
                <ArrowLeft size={16} />
                Back to Code Input
              </button>

              <div style={{ fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
                Active Session File: <strong style={{ color: "var(--text-primary)" }}>{lastInput.filename || "main.py"}</strong>
              </div>
            </div>

            <div className="dashboard-grid">
              
              {/* Left Column: Code Comparisons */}
              <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
                <DiffViewer
                  originalCode={lastInput.code}
                  finalCode={
                    repairResult?.result?.final_code || 
                    analyzeResult?.patcher_output?.patched_code || 
                    lastInput.code
                  }
                  filename={lastInput.filename}
                />
              </div>

              {/* Right Column: Agent Reports / Verification Telemetry */}
              <div>
                {/* Tabs */}
                <div className="tabs-container">
                  {mode === "repair" && (
                    <>
                      <button
                        type="button"
                        className={`tab-btn ${activeTab === "narrative" ? "active" : ""}`}
                        onClick={() => setActiveTab("narrative")}
                      >
                        <Award size={14} />
                        Narrative
                      </button>
                      <button
                        type="button"
                        className={`tab-btn ${activeTab === "critic" ? "active" : ""}`}
                        onClick={() => setActiveTab("critic")}
                      >
                        <ShieldCheck size={14} />
                        Semantic Critic
                      </button>
                      <button
                        type="button"
                        className={`tab-btn ${activeTab === "sandbox" ? "active" : ""}`}
                        onClick={() => setActiveTab("sandbox")}
                      >
                        <Terminal size={14} />
                        Sandbox Log
                      </button>
                    </>
                  )}
                  {mode === "analyze" && (
                    <>
                      <button
                        type="button"
                        className={`tab-btn ${activeTab === "trace" ? "active" : ""}`}
                        onClick={() => setActiveTab("trace")}
                      >
                        <Cpu size={14} />
                        Graph Trace
                      </button>
                    </>
                  )}
                </div>

                {/* Tab Contents */}
                <div>
                  {mode === "repair" && repairResult && (
                    <>
                      {activeTab === "narrative" && (
                        <ResultExplainer
                          explanation={repairResult.explanation}
                          status={repairResult.result.status}
                        />
                      )}
                      {activeTab === "critic" && (
                        <ResultCritic critique={repairResult.critique} />
                      )}
                      {activeTab === "sandbox" && (
                        <SandboxReport result={repairResult.result} />
                      )}
                    </>
                  )}

                  {mode === "analyze" && analyzeResult && (
                    <>
                      {activeTab === "trace" && (
                        <TraceViewer response={analyzeResult} />
                      )}
                    </>
                  )}
                </div>

              </div>

            </div>

          </div>
        )}
      </main>
    </div>
  );
}

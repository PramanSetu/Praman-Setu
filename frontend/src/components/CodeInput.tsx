import React, { useState } from "react";
import { Play, Settings, AlertTriangle, Code2, Sparkles, BookOpen } from "lucide-react";

interface CodeInputProps {
  loading: boolean;
  onRepair: (
    code: string,
    filename: string | null,
    errorMessage: string | null,
    maxPasses: number,
    explain: boolean,
    critique: boolean
  ) => void;
  onAnalyze: (code: string, filename: string | null, errorMessage: string | null) => void;
}

const EXAMPLES = [
  {
    name: "Runtime Crash (ZeroDivision)",
    filename: "calculator.py",
    error: "ZeroDivisionError: division by zero at line 6",
    code: `def calculate_average(scores):\n    total = sum(scores)\n    count = len(scores)\n    # Bug: Count might be zero, causing a crash\n    average = total / count\n    return average\n\n# Example usage\nprint(calculate_average([]))`,
  },
  {
    name: "Syntax Error (Broken Parse)",
    filename: "syntax_bug.py",
    error: "SyntaxError: expected ':' at line 3",
    code: `def check_admin(user)\n    if user == "admin"\n        return True\n    else\n        return False`,
  },
  {
    name: "Latent Logic Bug (Critic Target)",
    filename: "finance.py",
    error: "",
    code: `def calculate_interest(balance, rate_percent, years):\n    # Bug: Rate is used as direct multiplier rather than decimal\n    # Balance increases exponentially, but formulas like (1 + rate_percent) are wrong.\n    total = balance\n    for _ in range(years):\n        total = total * rate_percent\n    return total\n\nprint("Interest:", calculate_interest(1000, 5, 2))`,
  },
];

export function CodeInput({ loading, onRepair, onAnalyze }: CodeInputProps) {
  const [code, setCode] = useState(EXAMPLES[0].code);
  const [filename, setFilename] = useState(EXAMPLES[0].filename);
  const [errorMsg, setErrorMsg] = useState(EXAMPLES[0].error);
  const [maxPasses, setMaxPasses] = useState(3);
  const [explain, setExplain] = useState(true);
  const [critique, setCritique] = useState(true);
  const [strategy, setStrategy] = useState<"repair_v2" | "analyze">("repair_v2");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;

    if (strategy === "repair_v2") {
      onRepair(code, filename, errorMsg, maxPasses, explain, critique);
    } else {
      onAnalyze(code, filename, errorMsg);
    }
  };

  const loadExample = (index: number) => {
    const ex = EXAMPLES[index];
    setCode(ex.code);
    setFilename(ex.filename);
    setErrorMsg(ex.error);
  };

  // Generate line numbers
  const lineCount = code.split("\n").length;
  const lineNumbers = Array.from({ length: lineCount }, (_, i) => i + 1);

  return (
    <div className="glass-panel" style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 className="section-title" style={{ margin: 0 }}>
          <Code2 size={18} color="var(--accent-primary)" />
          <span>Source Code Input</span>
        </h2>
        
        <div style={{ display: "flex", gap: "0.5rem" }}>
          {EXAMPLES.map((ex, idx) => (
            <button
              key={idx}
              type="button"
              className="btn btn-secondary"
              style={{ padding: "0.25rem 0.625rem", fontSize: "0.75rem", display: "flex", alignItems: "center", gap: "0.25rem" }}
              onClick={() => loadExample(idx)}
            >
              <BookOpen size={12} />
              {ex.name.split(" ")[0]}
            </button>
          ))}
        </div>
      </div>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          <div className="form-group" style={{ margin: 0 }}>
            <label className="form-label">Filename</label>
            <input
              type="text"
              className="form-input"
              placeholder="e.g. main.py"
              value={filename}
              onChange={(e) => setFilename(e.target.value)}
            />
          </div>
          <div className="form-group" style={{ margin: 0 }}>
            <label className="form-label">Execution Strategy</label>
            <div style={{ display: "flex", border: "1px solid var(--border-color)", borderRadius: 8, overflow: "hidden", height: "38px" }}>
              <button
                type="button"
                style={{
                  flex: 1,
                  border: "none",
                  background: strategy === "repair_v2" ? "var(--bg-tertiary)" : "transparent",
                  color: strategy === "repair_v2" ? "var(--accent-primary)" : "var(--text-secondary)",
                  cursor: "pointer",
                  fontSize: "0.8125rem",
                  fontWeight: 600,
                }}
                onClick={() => setStrategy("repair_v2")}
              >
                Multi-Issue (v2)
              </button>
              <button
                type="button"
                style={{
                  flex: 1,
                  border: "none",
                  background: strategy === "analyze" ? "var(--bg-tertiary)" : "transparent",
                  color: strategy === "analyze" ? "var(--accent-primary)" : "var(--text-secondary)",
                  cursor: "pointer",
                  fontSize: "0.8125rem",
                  fontWeight: 600,
                }}
                onClick={() => setStrategy("analyze")}
              >
                Single Graph
              </button>
            </div>
          </div>
        </div>

        <div className="form-group" style={{ margin: 0 }}>
          <label className="form-label">Observed Error Message / Trace (Optional)</label>
          <input
            type="text"
            className="form-input"
            placeholder="e.g. NameError: name 'x' is not defined"
            style={{ fontFamily: "var(--font-mono)", fontSize: "0.78125rem" }}
            value={errorMsg}
            onChange={(e) => setErrorMsg(e.target.value)}
          />
        </div>

        <div className="form-group" style={{ margin: 0 }}>
          <label className="form-label">Python Source Code</label>
          <div className="code-editor-wrapper">
            <div className="code-editor-header">
              <div className="code-editor-title">
                <Code2 size={14} />
                <span>{filename || "untitled.py"}</span>
              </div>
            </div>
            
            <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
              {/* Line Numbers */}
              <div style={{
                padding: "1rem 0",
                width: "3rem",
                textAlign: "right",
                backgroundColor: "var(--bg-secondary)",
                color: "var(--text-muted)",
                userSelect: "none",
                fontFamily: "var(--font-mono)",
                fontSize: "0.8125rem",
                lineHeight: 1.5,
                borderRight: "1px solid var(--border-color)",
                overflow: "hidden"
              }}>
                {lineNumbers.map((num) => (
                  <div key={num} style={{ paddingRight: "0.75rem" }}>{num}</div>
                ))}
              </div>

              {/* Textarea */}
              <textarea
                className="code-textarea"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="# Paste your python code here..."
                spellCheck={false}
              />
            </div>
          </div>
        </div>

        {/* Advanced Config Toggles */}
        <div>
          <button
            type="button"
            className="btn btn-secondary"
            style={{ width: "100%", justifyContent: "space-between", padding: "0.5rem 1rem", fontSize: "0.8125rem" }}
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            <span style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <Settings size={14} />
              Advanced Parameters
            </span>
            <span>{showAdvanced ? "▲" : "▼"}</span>
          </button>

          {showAdvanced && (
            <div className="config-card" style={{ marginTop: "0.75rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {strategy === "repair_v2" ? (
                <>
                  <div className="config-toggle-row">
                    <span style={{ fontSize: "0.8125rem" }}>Max Loop Iterations (Passes)</span>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                      <input
                        type="range"
                        min="1"
                        max="5"
                        value={maxPasses}
                        onChange={(e) => setMaxPasses(parseInt(e.target.value))}
                        style={{ accentColor: "var(--accent-primary)" }}
                      />
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.875rem", width: "1.5rem", textAlign: "right" }}>
                        {maxPasses}
                      </span>
                    </div>
                  </div>

                  <div className="config-toggle-row">
                    <span style={{ fontSize: "0.8125rem" }}>Generate Semantic Explanation</span>
                    <label className="toggle-switch">
                      <input type="checkbox" checked={explain} onChange={(e) => setExplain(e.target.checked)} />
                      <span className="toggle-slider"></span>
                    </label>
                  </div>

                  <div className="config-toggle-row">
                    <span style={{ fontSize: "0.8125rem" }}>Run Critic Security & Logic Audit</span>
                    <label className="toggle-switch">
                      <input type="checkbox" checked={critique} onChange={(e) => setCritique(e.target.checked)} />
                      <span className="toggle-slider"></span>
                    </label>
                  </div>
                </>
              ) : (
                <div style={{ fontSize: "0.8125rem", color: "var(--text-secondary)", display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <AlertTriangle size={14} color="var(--status-unresolved)" />
                  <span>Single Graph executes the single-bug LangGraph orchestrator loop.</span>
                </div>
              )}
            </div>
          )}
        </div>

        <button
          type="submit"
          className="btn btn-primary"
          style={{ width: "100%", padding: "0.75rem" }}
          disabled={loading || !code.trim()}
        >
          {loading ? (
            <>
              <div className="spinner" style={{ width: 16, height: 16, borderThickness: "2px" }} />
              Processing Pipeline…
            </>
          ) : (
            <>
              {strategy === "repair_v2" ? <Sparkles size={16} /> : <Play size={16} />}
              {strategy === "repair_v2" ? "Run Automated Repair (V2)" : "Analyze in Agent Graph"}
            </>
          )}
        </button>
      </form>
    </div>
  );
}

import React, { useState, useRef } from "react";
import { Play, Sparkles, BookOpen, RotateCcw } from "lucide-react";
import { FileUpload } from "./FileUpload";

interface CodeInputProps {
  loading: boolean;
  code: string;
  filename: string | null;
  errorMsg: string;
  setCode: (c: string) => void;
  setFilename: (f: string | null) => void;
  setErrorMsg: (e: string) => void;
  onAnalyze: () => void;
  onReset: () => void;
}

export const EXAMPLES = [
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

export function CodeInput({
  loading,
  code,
  filename,
  errorMsg,
  setCode,
  setFilename,
  setErrorMsg,
  onAnalyze,
  onReset
}: CodeInputProps) {
  const lineNumbersRef = useRef<HTMLDivElement>(null);

  const handleFileLoad = (content: string, fname: string) => {
    setCode(content);
    setFilename(fname);
  };

  const handleClearFile = () => {
    setFilename(null);
  };

  const loadExample = (index: number) => {
    const ex = EXAMPLES[index];
    setCode(ex.code);
    setFilename(ex.filename);
    setErrorMsg(ex.error);
  };

  const lineCount = code.split("\n").length;
  const lineNumbers = Array.from({ length: Math.max(25, lineCount) }, (_, i) => i + 1);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.875rem" }}>
      
      {/* File Upload Zone */}
      <div>
        <label className="form-label" style={{ marginBottom: "0.125rem" }}>Import Source File</label>
        <FileUpload
          onFileLoad={handleFileLoad}
          selectedFilename={filename}
          onClear={handleClearFile}
        />
      </div>

      {/* Examples Row */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.375rem" }}>
        {EXAMPLES.map((ex, idx) => (
          <button
            key={idx}
            type="button"
            className="btn btn-secondary"
            style={{
              padding: "0.25rem 0.5rem",
              fontSize: "0.725rem",
              display: "flex",
              alignItems: "center",
              gap: "0.25rem",
              borderRadius: "4px"
            }}
            onClick={() => loadExample(idx)}
          >
            <BookOpen size={10} />
            {ex.name.split(" ")[0]} Example
          </button>
        ))}
      </div>

      {/* Code Editor */}
      <div>
        <label className="form-label">Python Source Code</label>
        <div className="code-editor-wrapper" style={{ height: "360px" }}>
          <div className="code-editor-header" style={{ padding: "0.5rem 0.75rem" }}>
            <div className="code-editor-title" style={{ fontSize: "0.75rem" }}>
              <span>{filename || "scratchpad.py"}</span>
            </div>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
              {lineCount} lines
            </span>
          </div>
          
          <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
            {/* Line Numbers */}
            <div
              ref={lineNumbersRef}
              style={{
                padding: "0.75rem 0",
                width: "2.5rem",
                textAlign: "right",
                backgroundColor: "#0d1117",
                color: "var(--text-muted)",
                userSelect: "none",
                fontFamily: "var(--font-mono)",
                fontSize: "0.78125rem",
                lineHeight: 1.5,
                borderRight: "1px solid var(--border-color)",
                overflow: "hidden"
              }}
            >
              {lineNumbers.map((num) => (
                <div key={num} style={{ paddingRight: "0.5rem" }}>{num}</div>
              ))}
            </div>

            {/* Textarea */}
            <textarea
              className="code-textarea"
              style={{
                backgroundColor: "#0d1117",
                padding: "0.75rem",
                fontSize: "0.78125rem",
                lineHeight: 1.5,
                color: "#e6edf3"
              }}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              onScroll={(e) => {
                if (lineNumbersRef.current) {
                  lineNumbersRef.current.scrollTop = e.currentTarget.scrollTop;
                }
              }}
              placeholder="# Paste Python code here or drag in a file..."
              spellCheck={false}
            />
          </div>
        </div>
      </div>

      {/* Error Message field */}
      <div>
        <label className="form-label">Observed Error Message / Traceback (Optional)</label>
        <textarea
          className="form-textarea"
          style={{ height: "65px", fontSize: "0.75rem", padding: "0.5rem" }}
          placeholder="e.g. ValueError: math domain error at line 4"
          value={errorMsg}
          onChange={(e) => setErrorMsg(e.target.value)}
        />
      </div>

      {/* Actions */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: "0.5rem", marginTop: "0.25rem" }}>
        <button
          type="button"
          className="btn btn-primary"
          style={{ padding: "0.625rem" }}
          disabled={loading || !code.trim()}
          onClick={onAnalyze}
        >
          {loading ? (
            <>
              <div className="timeline-spin" style={{ width: 14, height: 14, border: "2px solid rgba(255, 255, 255, 0.2)", borderTopColor: "white", borderRadius: "50%" }} />
              Running Agent graph…
            </>
          ) : (
            <>
              <Sparkles size={14} />
              Analyze & Fix
            </>
          )}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          style={{ padding: "0.625rem" }}
          onClick={onReset}
          disabled={loading}
        >
          <RotateCcw size={14} />
          Reset
        </button>
      </div>

    </div>
  );
}

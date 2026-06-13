import React from "react";
import { CheckCircle2, XCircle, Code, FileText, ChevronRight } from "lucide-react";

interface TestsTabProps {
  generatedTest: string;
  testPassed: boolean;
  testOutput: string;
  existingTestDelta: string;
}

export function TestsTab({
  generatedTest,
  testPassed,
  testOutput,
  existingTestDelta
}: TestsTabProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      
      {/* Test Status Banner */}
      <div style={{
        padding: "0.75rem 1rem",
        borderRadius: 6,
        backgroundColor: testPassed ? "var(--status-clean-glow)" : "var(--status-error-glow)",
        border: `1px solid ${testPassed ? "rgba(34, 197, 94, 0.15)" : "rgba(239, 68, 68, 0.15)"}`,
        display: "flex",
        alignItems: "center",
        gap: "0.625rem",
      }}>
        {testPassed ? (
          <CheckCircle2 size={18} color="var(--status-clean)" />
        ) : (
          <XCircle size={18} color="var(--status-error)" />
        )}
        <div>
          <h4 style={{ fontSize: "0.8125rem", fontWeight: 700, color: "white" }}>
            {testPassed ? "All Sandbox Tests Passed" : "Sandbox Test Regressions Detected"}
          </h4>
          <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "0.05rem" }}>
            Dynamic assertions executed within the hardened Python container pool.
          </p>
        </div>
      </div>

      {/* Generated Test Code Block */}
      <div>
        <h4 style={{ fontSize: "0.75rem", color: "white", display: "flex", alignItems: "center", gap: "0.375rem", marginBottom: "0.375rem" }}>
          <Code size={12} color="var(--accent-purple)" />
          Generated Assertion Test Suite
        </h4>
        <pre className="code-pre" style={{
          backgroundColor: "var(--bg-primary)",
          border: "1px solid var(--border-color)",
          borderRadius: 6,
          maxHeight: "180px",
          overflowY: "auto"
        }}>
          <code>{generatedTest || "# No verification test was synthesized."}</code>
        </pre>
      </div>

      {/* Pytest Console Output wrapped in Terminal Mockup */}
      <div>
        <h4 style={{ fontSize: "0.75rem", color: "white", display: "flex", alignItems: "center", gap: "0.375rem", marginBottom: "0.375rem" }}>
          <FileText size={12} color="var(--accent-primary)" />
          Sandbox Execution Terminal Log
        </h4>
        
        <div className="terminal-box">
          <div className="terminal-header">
            <span>bash - pytest validator_sandbox_run.py</span>
            <div style={{ display: "flex", gap: "0.25rem", alignItems: "center" }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: "#ef4444", display: "inline-block" }}></span>
              <span style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: "#eab308", display: "inline-block" }}></span>
              <span style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: "#22c55e", display: "inline-block" }}></span>
            </div>
          </div>
          <div className="terminal-content">
            {testOutput || "Console is empty. Execution returned exit status 0."}
          </div>
        </div>
      </div>

      {/* Existing Test Delta */}
      {existingTestDelta && (
        <div style={{
          padding: "0.625rem 0.875rem",
          borderRadius: 6,
          backgroundColor: "var(--bg-primary)",
          border: "1px solid var(--border-color)",
          fontSize: "0.75rem",
          display: "flex",
          alignItems: "center",
          gap: "0.5rem"
        }}>
          <ChevronRight size={12} color="var(--text-secondary)" />
          <span style={{ color: "var(--text-secondary)" }}>Regression Delta:</span>
          <strong style={{ color: testPassed ? "var(--status-clean)" : "var(--status-error)", fontFamily: "var(--font-mono)" }}>
            {existingTestDelta}
          </strong>
        </div>
      )}
    </div>
  );
}

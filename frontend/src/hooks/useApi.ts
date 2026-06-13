import { useState, useEffect } from "react";

// Fallback to localhost if host is not specified, but default to the current domain's port 8000
const getApiBase = () => {
  if (typeof window !== "undefined") {
    const hostname = window.location.hostname;
    return `http://${hostname}:8000`;
  }
  return "http://localhost:8000";
};

export const API_BASE = getApiBase();

export interface HealthInfo {
  status: string;
  default_provider: string;
  groq_configured: boolean;
  sandbox_timeout: number;
  sandbox_pool_warmed: boolean;
  sandbox_pool_idle: number;
  checkpointing: boolean;
}

export interface LedgerIssue {
  kind: "syntax" | "runtime" | "undefined_name_hint" | "top_level_input" | "top_level_execution";
  line: number | null;
  symbol: string | null;
  message: string;
  severity: "error" | "warning" | "info";
}

export interface SymbolInfo {
  name: string;
  line: number;
}

export interface BugLedger {
  code_compiles: boolean;
  issues: LedgerIssue[];
  imports: string[];
  functions: SymbolInfo[];
  classes: SymbolInfo[];
  top_level_executable_lines: number[];
  top_level_input_lines: number[];
  runtime_error_type: string | null;
  runtime_error_line: number | null;
  runtime_error_message: string;
  crash_locals: Record<string, string> | null;
}

export interface RepairAttempt {
  pass_number: number;
  summary: string;
  issues_found: string[];
  applied_edits: number;
  edit_failures: string[];
  validation_errors: string[];
  confidence: number;
}

export interface RepairV2Result {
  status: "clean" | "unresolved" | "no_progress" | "insecure";
  passes: number;
  original_code: string;
  final_code: string;
  ledger: BugLedger;
  attempts: RepairAttempt[];
  remaining_error: string | null;
}

export interface FixDetail {
  issue: string;
  fix: string;
  category: string;
}

export interface RepairExplanation {
  status: string;
  headline: string;
  fixes: FixDetail[];
  flagged: string[];
  verification: string;
}

export interface FixAssessment {
  target: string;
  addresses_root_cause: boolean;
  preserves_intent: boolean;
  confidence: "high" | "medium" | "low";
  concern: string;
}

export interface LogicConcern {
  location: string;
  issue: string;
  severity: "high" | "medium" | "low";
}

export interface CritiqueReport {
  overall: "solid" | "acceptable" | "risky" | "unassessed";
  summary: string;
  assessments: FixAssessment[];
  logic_audit: LogicConcern[];
  needs_human_review: string[];
}

export interface RepairV2Response {
  result: RepairV2Result;
  explanation: RepairExplanation | null;
  critique: CritiqueReport | null;
}

// Phase 1 Graph Types
export interface Hypothesis {
  id: string;
  theory: string;
  confidence: number;
  fix_direction: string;
  evidence: string[];
  risk_if_wrong: string;
}

export interface DiagnoserOutput {
  root_cause: string;
  affected_scope: "local" | "caller" | "callee" | "class" | "module" | "unknown";
  evidence: string[];
  hypotheses: Hypothesis[];
  generated_test: string;
  test_assertion_summary: string;
  requires_clarification: boolean;
  clarification_question: string | null;
}

export interface PatcherOutput {
  unified_diff: string;
  confidence: number;
  approach: string;
  patch_target: "function" | "caller" | "callee" | "class" | "module";
  patch_target_source: string;
  hypothesis_used: string;
  lines_changed: number;
  potential_side_effects: string[];
  api_signature_preserved: boolean;
  new_imports_required: string[];
  blocked_reason: string | null;
  patched_code: string;
}

export interface GateResult {
  passed: boolean;
  error: string | null;
  duration_s: number;
}

export interface SafetyFinding {
  rule: string;
  severity: string;
  line: number | null;
}

export interface SafetyDiff {
  introduced: SafetyFinding[];
  fixed: SafetyFinding[];
  verdict: "improvement" | "neutral" | "regression" | "tradeoff";
}

export interface ValidatorReport {
  overall_passed: boolean;
  gate_results: Record<string, GateResult>;
  safety_diff: SafetyDiff | null;
  summary: string;
  detailed_failures: string[];
}

export interface LLMCallMetric {
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
}

export interface RunTrace {
  input_handler_ms: number;
  total_ms: number;
  nodes: Array<{ name: string; duration_ms: number }>;
  llm_calls: LLMCallMetric[];
}

export interface AnalyzeResponse {
  status: string;
  diagnoser_output: DiagnoserOutput | null;
  patcher_output: PatcherOutput | null;
  validator_report: ValidatorReport | null;
  retry_count: number;
  human_review_flag: boolean;
  hypothesis_used: string;
  patch_history: PatcherOutput[];
  validation_history: ValidatorReport[];
  patcher_prompts: string[];
  trace?: RunTrace;
}

export function useApi() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [healthStatus, setHealthStatus] = useState<"checking" | "online" | "offline">("checking");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [repairResult, setRepairResult] = useState<RepairV2Response | null>(null);
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResponse | null>(null);
  const [mode, setMode] = useState<"repair" | "analyze">("repair");

  const checkHealth = async () => {
    try {
      const res = await fetch(`${API_BASE}/health`);
      if (res.ok) {
        const data = await res.json();
        setHealth(data);
        setHealthStatus("online");
      } else {
        setHealthStatus("offline");
      }
    } catch (e) {
      setHealthStatus("offline");
    }
  };

  // Poll health status on mount
  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  const runRepair = async (
    code: string,
    filename: string | null,
    errorMessage: string | null,
    maxPasses: number = 3,
    explain: boolean = true,
    critique: boolean = true
  ) => {
    setLoading(true);
    setError(null);
    setRepairResult(null);
    setAnalyzeResult(null);
    setMode("repair");

    try {
      const url = new URL(`${API_BASE}/api/repair-v2`);
      url.searchParams.append("max_passes", maxPasses.toString());
      url.searchParams.append("explain", explain.toString());
      url.searchParams.append("critique", critique.toString());

      const response = await fetch(url.toString(), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          code,
          filename: filename || null,
          error_message: errorMessage || null,
        }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned error status ${response.status}`);
      }

      const data: RepairV2Response = await response.json();
      setRepairResult(data);
    } catch (err: any) {
      setError(err.message || "Failed to process code repair.");
    } finally {
      setLoading(false);
    }
  };

  const runAnalyze = async (
    code: string,
    filename: string | null,
    errorMessage: string | null,
    debug: boolean = true
  ) => {
    setLoading(true);
    setError(null);
    setRepairResult(null);
    setAnalyzeResult(null);
    setMode("analyze");

    try {
      const url = new URL(`${API_BASE}/api/analyze`);
      url.searchParams.append("debug", debug.toString());

      const response = await fetch(url.toString(), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          code,
          filename: filename || null,
          error_message: errorMessage || null,
        }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned error status ${response.status}`);
      }

      const data: AnalyzeResponse = await response.json();
      setAnalyzeResult(data);
    } catch (err: any) {
      setError(err.message || "Failed to analyze code.");
    } finally {
      setLoading(false);
    }
  };

  return {
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
    clearResults: () => {
      setRepairResult(null);
      setAnalyzeResult(null);
    }
  };
}

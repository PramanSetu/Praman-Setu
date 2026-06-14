import { useEffect, useRef, useState } from "react";
import Editor, { DiffEditor, type Monaco } from "@monaco-editor/react";
import "./App.css";

const API = "http://localhost:8000";

const MONACO_BASE_OPTIONS = {
  fontSize: 13,
  fontFamily: '"JetBrains Mono", "Cascadia Code", Consolas, monospace',
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  automaticLayout: true,
  tabSize: 4,
  smoothScrolling: true,
  padding: { top: 12, bottom: 12 },
};

function defineMonacoTheme(monaco: Monaco) {
  monaco.editor.defineTheme("praman", {
    base: "vs-dark",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#00000000",
      "editorGutter.background": "#00000000",
      "minimap.background": "#00000000",
      "editorLineNumber.foreground": "#6e7681",
      "editorLineNumber.activeForeground": "#cccccc",
    },
  });
}

const STAGES = [
  "Smart Input Handler",
  "Bug Ledger",
  "Repair Agent",
  "Patch Applier",
  "Validator",
  "Explainer Agent",
  "Critic Agent",
  "Property Tester",
] as const;

type StageName = (typeof STAGES)[number];
type StageState = "pending" | "running" | "done" | "failed" | "skipped";
type RunStatus = "idle" | "running" | "clean" | "unresolved" | "no_progress" | "insecure" | "error";
type Tab = "final" | "issues" | "attempts" | "explanation" | "review";

type LedgerIssue = {
  kind?: string;
  line?: number | null;
  symbol?: string | null;
  message?: string;
  severity?: string;
};

type RepairAttempt = {
  pass_number?: number;
  summary?: string;
  issues_found?: string[];
  applied_edits?: number;
  edit_failures?: string[];
  validation_errors?: string[];
  confidence?: number;
};

type FixDetail = {
  issue?: string;
  fix?: string;
  category?: string;
};

type Explanation = {
  headline?: string;
  fixes?: FixDetail[];
  flagged?: string[];
  verification?: string;
};

type FixAssessment = {
  target?: string;
  addresses_root_cause?: boolean;
  preserves_intent?: boolean;
  confidence?: string;
  concern?: string;
};

type LogicConcern = {
  location?: string;
  axis?: string;
  issue?: string;
  severity?: string;
  needs_intent?: boolean;
};

type Critique = {
  overall?: string;
  summary?: string;
  assessments?: FixAssessment[];
  logic_audit?: LogicConcern[];
  needs_human_review?: string[];
};

type ProvenIssue = {
  test?: string;
  detail?: string;
};

type PropertyReport = {
  status?: string;
  summary?: string;
  proven_issues?: ProvenIssue[];
};

type Finding = {
  tier?: string;
  category?: string;
  location?: string;
  detail?: string;
  source?: string;
};

type ResultPayload = {
  status?: RunStatus;
  passes?: number;
  original_code?: string;
  final_code?: string;
  remaining_error?: string | null;
  ledger?: {
    issues?: LedgerIssue[];
  };
  attempts?: RepairAttempt[];
};

const SAMPLE_CODE = `def summarize(items)
    report = []
    for i in range(len(itmes) + 1):
        item = items[i]
        price = item["price"]
        tax = item["tax"]
        report.appnd(price + tax)
    return report

def average(values):
    total = 0
    count = 0
    for v in values:
        total += v
    return total / count

print(summarize([{"price": 100, "tax": 18}]))
print(average([10, 20, 30]))`;

export function App() {
  const [health, setHealth] = useState("checking");
  const [provider, setProvider] = useState("");
  const [filename] = useState("app.py");
  const [errorMessage, setErrorMessage] = useState("");
  const [code, setCode] = useState(SAMPLE_CODE);
  const [maxPasses] = useState(3);
  const [explain] = useState(true);
  const [critiqueEnabled] = useState(true);
  const [status, setStatus] = useState<RunStatus>("idle");
  const [activeTab, setActiveTab] = useState<Tab>("final");
  const [activeStage, setActiveStage] = useState<StageName | null>(null);
  const [stageStates, setStageStates] = useState<Record<StageName, StageState>>(() =>
    Object.fromEntries(STAGES.map((stage) => [stage, "pending"])) as Record<StageName, StageState>,
  );
  const [latestCode, setLatestCode] = useState("");
  const [issues, setIssues] = useState<LedgerIssue[]>([]);
  const [attempts, setAttempts] = useState<RepairAttempt[]>([]);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [critique, setCritique] = useState<Critique | null>(null);
  const [property, setProperty] = useState<PropertyReport | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [result, setResult] = useState<ResultPayload | null>(null);
  const [streamLog, setStreamLog] = useState<string[]>([]);
  const [, setRunError] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    fetch(`${API}/health`)
      .then((response) => response.json())
      .then((data: Record<string, unknown>) => {
        setHealth("online");
        setProvider(String(data.default_provider ?? "unknown"));
      })
      .catch(() => {
        setHealth("offline");
        setProvider("");
      });
  }, []);

  const displayCode = result?.final_code ?? latestCode;
  // Hide INFO-level ledger context markers (top_level_execution / top_level_input)
  // — they're agent context, not user-facing bugs. Show only error/warning issues.
  const realIssues = issues.filter((issue) => (issue.severity ?? "info") !== "info");
  const isRunning = status === "running";

  async function repair() {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    resetRunState();
    setStatus("running");
    setStreamLog(["Opening repair stream"]);

    try {
      const params = new URLSearchParams({
        max_passes: String(maxPasses),
        explain: String(explain),
        critique: String(critiqueEnabled),
      });
      const response = await fetch(`${API}/api/repair-v2/stream?${params.toString()}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify({
          code,
          filename,
          error_message: errorMessage || null,
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`Backend returned ${response.status}`);
      }

      await readSse(response.body, handleStreamEvent);
    } catch (error) {
      if ((error as Error).name === "AbortError") {
        return;
      }
      setStatus("error");
      setRunError((error as Error).message || "Repair stream failed");
      markStage(activeStage, "failed");
    }
  }

  function resetRunState() {
    setRunError("");
    setActiveStage(null);
    setLatestCode("");
    setIssues([]);
    setAttempts([]);
    setExplanation(null);
    setCritique(null);
    setProperty(null);
    setFindings([]);
    setResult(null);
    setStageStates(
      Object.fromEntries(STAGES.map((stage) => [stage, "pending"])) as Record<StageName, StageState>,
    );
  }

  function handleStreamEvent(eventType: string, payload: Record<string, unknown>) {
    setStreamLog((items) => [`${eventType}: ${stageFrom(payload) ?? "update"}`, ...items].slice(0, 8));

    if (eventType === "phase") {
      const stage = toStage(payload.stage);
      if (stage) {
        setActiveStage(stage);
        markStage(stage, "running");
      }
      return;
    }

    if (eventType === "input") {
      completeStage("Smart Input Handler");
      return;
    }

    if (eventType === "ledger") {
      completeStage("Bug Ledger");
      const ledger = payload.ledger as { issues?: LedgerIssue[] } | undefined;
      setIssues(Array.isArray(ledger?.issues) ? ledger.issues : []);
      return;
    }

    if (eventType === "repair") {
      completeStage("Repair Agent");
      return;
    }

    if (eventType === "patch") {
      completeStage("Patch Applier");
      setLatestCode(String(payload.code ?? ""));
      setActiveTab("final");
      return;
    }

    if (eventType === "validation") {
      completeStage("Validator");
      if (payload.passed === false) {
        markStage("Validator", "failed");
      }
      return;
    }

    if (eventType === "attempt") {
      const attempt = payload.attempt as RepairAttempt | undefined;
      if (attempt) {
        setAttempts((current) => upsertAttempt(current, attempt));
      }
      return;
    }

    if (eventType === "explanation") {
      completeStage("Explainer Agent");
      setExplanation((payload.explanation as Explanation | undefined) ?? null);
      return;
    }

    if (eventType === "critique") {
      completeStage("Critic Agent");
      setCritique((payload.critique as Critique | undefined) ?? null);
      return;
    }

    if (eventType === "property") {
      completeStage("Property Tester");
      setProperty((payload.property as PropertyReport | undefined) ?? null);
      return;
    }

    if (eventType === "done") {
      const nextResult = payload.result as ResultPayload | undefined;
      setResult(nextResult ?? null);
      setStatus(nextResult?.status ?? "clean");
      setIssues(nextResult?.ledger?.issues ?? issues);
      setAttempts(nextResult?.attempts ?? attempts);
      setLatestCode(nextResult?.final_code ?? latestCode);
      setExplanation((payload.explanation as Explanation | null) ?? explanation);
      setCritique((payload.critique as Critique | null) ?? critique);
      setProperty((payload.property as PropertyReport | null) ?? property);
      setFindings((payload.findings as Finding[] | undefined) ?? []);
      setActiveStage(null);
      // Finalize the strip: a stage that never ran was skipped (e.g. Repair Agent
      // and Patch Applier when the code was already clean), and any still-running
      // stage is now done.
      setStageStates((current) => {
        const next = { ...current };
        for (const stage of STAGES) {
          if (next[stage] === "pending") {
            next[stage] = "skipped";
          } else if (next[stage] === "running") {
            next[stage] = "done";
          }
        }
        return next;
      });
      return;
    }

    if (eventType === "error") {
      setStatus("error");
      setRunError(String(payload.message ?? "Repair failed"));
      markStage(activeStage, "failed");
    }
  }

  function completeStage(stage: StageName) {
    markStage(stage, "done");
    if (activeStage === stage) {
      setActiveStage(null);
    }
  }

  function markStage(stage: StageName | null, state: StageState) {
    if (!stage) {
      return;
    }
    setStageStates((current) => ({ ...current, [stage]: state }));
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-row">
          <button className="primary-button" disabled={isRunning || !code.trim()} onClick={repair}>
            {isRunning ? "Repairing…" : "Repair"}
          </button>
          <span className="divider" />
          <strong className="brand">Praman Setu</strong>
        </div>
        <div className="brand-row">
          <span className={`health-dot ${health}`} />
          <span className="top-meta">Backend: {health}</span>
          {provider && <span className="top-meta">Provider: {provider}</span>}
        </div>
      </header>

      <Pipeline stages={stageStates} activeStage={activeStage} />

      <section className="workspace">
        <section className="panel input-panel">
          <div className="input-meta">
            <label>
              <input
                className="error-input"
                value={errorMessage}
                onChange={(event) => setErrorMessage(event.target.value)}
                placeholder="Optional error message or traceback"
              />
            </label>
          </div>

          <div className="editor-wrap">
            <Editor
              height="100%"
              language="python"
              theme="praman"
              value={code}
              onChange={(value) => setCode(value ?? "")}
              beforeMount={defineMonacoTheme}
              options={MONACO_BASE_OPTIONS}
            />
          </div>

        </section>

        <section className="panel results-panel">
          <nav className="tabs">
            <TabButton active={activeTab === "final"} onClick={() => setActiveTab("final")}>
              Final Code
            </TabButton>
            <TabButton active={activeTab === "issues"} onClick={() => setActiveTab("issues")}>
              Issues {realIssues.length ? `(${realIssues.length})` : ""}
            </TabButton>
            <TabButton active={activeTab === "attempts"} onClick={() => setActiveTab("attempts")}>
              Attempts {attempts.length ? `(${attempts.length})` : ""}
            </TabButton>
            <TabButton active={activeTab === "explanation"} onClick={() => setActiveTab("explanation")}>
              Explanation
            </TabButton>
            <TabButton active={activeTab === "review"} onClick={() => setActiveTab("review")}>
              Human Review {findings.length ? `(${findings.length})` : ""}
            </TabButton>
          </nav>

          <div className="tab-content">
            {activeTab === "final" && <FinalCode original={code} code={displayCode} />}
            {activeTab === "issues" && <Issues issues={realIssues} />}
            {activeTab === "attempts" && <Attempts attempts={attempts} />}
            {activeTab === "explanation" && <ExplanationPanel explanation={explanation} />}
            {activeTab === "review" && <ReviewPanel critique={critique} findings={findings} />}
          </div>

          <footer className="stream-footer">
            <span>Stream</span>
            {streamLog.map((entry) => (
              <code key={entry}>{entry}</code>
            ))}
          </footer>
        </section>
      </section>
    </main>
  );
}

function Pipeline({
  stages,
  activeStage,
}: {
  stages: Record<StageName, StageState>;
  activeStage: StageName | null;
}) {
  return (
    <section className="pipeline-strip">
      {STAGES.map((stage, index) => (
        <div className="stage-wrap" key={stage}>
          <div className={`stage ${stages[stage]} ${activeStage === stage ? "active" : ""}`}>
            <span>{index + 1}</span>
            {stage}
          </div>
          {index < STAGES.length - 1 && <span className="chevron">/</span>}
        </div>
      ))}
    </section>
  );
}

function TabButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button className={active ? "active" : ""} onClick={onClick}>
      {children}
    </button>
  );
}

function FinalCode({ original, code }: { original: string; code: string }) {
  if (!code) {
    return (
      <EmptyState
        title="No patched code yet"
        detail="The repaired file — with added/removed lines highlighted — appears when the stream completes."
      />
    );
  }
  // GitHub-style inline diff: removed (-) lines belong to the ORIGINAL model and
  // are shown as red view-zones, so selecting/copying the panel yields only the
  // kept + added lines (the clean patched code). The Copy button copies it too.
  return (
    <div className="monaco-fill code-card">
      <button className="copy-button" onClick={() => void navigator.clipboard.writeText(code)}>
        Copy patched code
      </button>
      <DiffEditor
        height="100%"
        language="python"
        theme="praman"
        original={original}
        modified={code}
        beforeMount={defineMonacoTheme}
        options={{
          ...MONACO_BASE_OPTIONS,
          readOnly: true,
          renderSideBySide: false,
          renderMarginRevertIcon: false,
          diffWordWrap: "off",
        }}
      />
    </div>
  );
}

function Issues({ issues }: { issues: LedgerIssue[] }) {
  if (!issues.length) {
    return <EmptyState title="No issues loaded" detail="Bug Ledger findings will appear after the input pass." />;
  }
  return (
    <div className="list-stack">
      {issues.map((issue, index) => (
        <article className="issue-card" key={`${issue.kind}-${issue.line}-${index}`}>
          <div>
            <span className={`pill ${issue.severity ?? "info"}`}>{issue.severity ?? "info"}</span>
            <strong>{issue.kind ?? "issue"}</strong>
          </div>
          <p>{issue.message ?? "No message provided"}</p>
          <small>
            Line {issue.line ?? "unknown"}
            {issue.symbol ? ` | ${issue.symbol}` : ""}
          </small>
        </article>
      ))}
    </div>
  );
}

function Attempts({ attempts }: { attempts: RepairAttempt[] }) {
  if (!attempts.length) {
    return <EmptyState title="No attempts yet" detail="Repair passes will be appended as the stream progresses." />;
  }
  return (
    <div className="list-stack">
      {attempts.map((attempt, index) => (
        <article className="attempt-card" key={`${attempt.pass_number}-${index}`}>
          <div className="attempt-head">
            <strong>Pass {attempt.pass_number ?? index + 1}</strong>
            <span>{percent(attempt.confidence)} confidence</span>
          </div>
          <p>{attempt.summary ?? "No summary provided"}</p>
          <dl>
            <dt>Applied edits</dt>
            <dd>{attempt.applied_edits ?? 0}</dd>
            <dt>Edit failures</dt>
            <dd>{attempt.edit_failures?.length ? attempt.edit_failures.join("; ") : "none"}</dd>
            <dt>Validation errors</dt>
            <dd>{attempt.validation_errors?.length ? attempt.validation_errors.join("; ") : "none"}</dd>
          </dl>
        </article>
      ))}
    </div>
  );
}

function ExplanationPanel({ explanation }: { explanation: Explanation | null }) {
  if (!explanation) {
    return <EmptyState title="No explanation yet" detail="The Explainer Agent runs after validation." />;
  }
  return (
    <div className="list-stack">
      <article className="summary-card">
        <strong>{explanation.headline ?? "Repair explained"}</strong>
        <p>{explanation.verification}</p>
      </article>
      {(explanation.fixes ?? []).map((fix, index) => (
        <article className="issue-card" key={`${fix.category}-${index}`}>
          <span className="pill info">{fix.category ?? "bug"}</span>
          <strong>{fix.issue}</strong>
          <p>{fix.fix}</p>
        </article>
      ))}
      {(explanation.flagged ?? []).map((item) => (
        <article className="issue-card warning" key={item}>
          <strong>Flagged</strong>
          <p>{item}</p>
        </article>
      ))}
    </div>
  );
}

const TIERS: { key: string; label: string; pill: string; card: string }[] = [
  { key: "confirmed", label: "Confirmed bugs", pill: "high", card: "proven" },
  { key: "likely", label: "Likely bugs", pill: "medium", card: "warning" },
  { key: "potential", label: "Potential issues", pill: "low", card: "" },
  { key: "style", label: "Style suggestions", pill: "unassessed", card: "" },
];

function ReviewPanel({ critique, findings }: { critique: Critique | null; findings: Finding[] }) {
  const assessments = critique?.assessments ?? [];

  if (!findings.length && !critique) {
    return <EmptyState title="No findings" detail="The reviewers' classified findings appear here." />;
  }

  return (
    <div className="list-stack">
      {critique && (
        <article className="summary-card">
          <div className="card-head">
            <span className={`pill ${critique.overall ?? "unassessed"}`}>{critique.overall ?? "unassessed"}</span>
            <span className="card-head-label">Semantic review</span>
          </div>
          <p>{critique.summary ?? "Semantic review complete."}</p>
        </article>
      )}

      {findings.length === 0 && <p className="muted" style={{ padding: "0 12px" }}>No latent issues found.</p>}

      {TIERS.map((tier) => {
        const items = findings.filter((f) => (f.tier ?? "potential") === tier.key);
        if (!items.length) {
          return null;
        }
        return (
          <Section title={tier.label} count={items.length} key={tier.key}>
            {items.map((f, index) => (
              <article className={`issue-card ${tier.card}`} key={`${tier.key}-${index}`}>
                <div className="card-head">
                  <span className={`pill ${tier.pill}`}>{tier.key}</span>
                  {f.category && f.category !== "other" && f.category !== "property" && (
                    <span className="axis-tag">{f.category.replace(/_/g, " ")}</span>
                  )}
                  {f.location && <code className="card-target">{f.location}</code>}
                </div>
                <p>{f.detail ?? ""}</p>
              </article>
            ))}
          </Section>
        );
      })}

      {assessments.length > 0 && (
        <Section title="Fix assessments" count={assessments.length}>
          {assessments.map((item, index) => (
            <article className="issue-card" key={`assessment-${index}`}>
              <div className="card-head">
                <code className="card-target">{item.target ?? `fix ${index + 1}`}</code>
                <span className={`pill ${confidenceTone(item.confidence)}`}>{item.confidence ?? "?"} confidence</span>
              </div>
              <div className="verdict-row">
                <Verdict label="Root cause" ok={item.addresses_root_cause} />
                <Verdict label="Intent kept" ok={item.preserves_intent} />
              </div>
              {item.concern && <p>{item.concern}</p>}
            </article>
          ))}
        </Section>
      )}
    </div>
  );
}

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <div className="review-section">
      <h2 className="section-title">
        {title} <span className="section-count">{count}</span>
      </h2>
      {children}
    </div>
  );
}

function Verdict({ label, ok }: { label: string; ok?: boolean }) {
  const state = ok === undefined ? "unknown" : ok ? "ok" : "bad";
  const mark = ok === undefined ? "?" : ok ? "✓" : "✗";
  return (
    <span className={`verdict ${state}`}>
      <span className="verdict-mark">{mark}</span>
      {label}
    </span>
  );
}

function confidenceTone(confidence?: string) {
  if (confidence === "high") return "solid";
  if (confidence === "low") return "warning";
  return "medium";
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

async function readSse(
  body: ReadableStream<Uint8Array>,
  onEvent: (eventType: string, payload: Record<string, unknown>) => void,
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const eventText of events) {
      const parsed = parseSseEvent(eventText);
      if (parsed) {
        onEvent(parsed.eventType, parsed.payload);
      }
    }
  }
}

function parseSseEvent(raw: string): { eventType: string; payload: Record<string, unknown> } | null {
  const lines = raw.split("\n");
  const eventType = lines.find((line) => line.startsWith("event:"))?.slice(6).trim() ?? "message";
  const data = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) {
    return null;
  }
  try {
    return { eventType, payload: JSON.parse(data) as Record<string, unknown> };
  } catch {
    return { eventType, payload: { message: data } };
  }
}

function toStage(value: unknown): StageName | null {
  return STAGES.includes(value as StageName) ? (value as StageName) : null;
}

function stageFrom(payload: Record<string, unknown>) {
  return typeof payload.stage === "string" ? payload.stage : null;
}

function upsertAttempt(attempts: RepairAttempt[], next: RepairAttempt) {
  const passNumber = next.pass_number;
  if (passNumber === undefined) {
    return [...attempts, next];
  }
  const index = attempts.findIndex((attempt) => attempt.pass_number === passNumber);
  if (index === -1) {
    return [...attempts, next];
  }
  return attempts.map((attempt, currentIndex) => (currentIndex === index ? next : attempt));
}

function percent(value: number | undefined) {
  if (value === undefined) {
    return "n/a";
  }
  return `${Math.round(value * 100)}%`;
}

# Code Generation + Debug Assistant — Final Unified Architecture

**Constraints:** No build deadline. Latency, performance, and quality remain primary.
**Decision basis:** Unbiased synthesis of both prior architectures, with every choice individually justified.
**Document version:** 2.0 (supersedes ARCHITECTURE.md)

---

## 0. What Changed When We Removed The Time Constraint

The previous architecture was implicitly compromised in 7 places by the 5-day build window. With unlimited build time but **continued focus on speed/latency/performance**, these change:

| Decision | Hackathon version | Final version | Why |
|---|---|---|---|
| Critic agent | Cut (saved build time) | **Brought back, runs in parallel with Explainer** | Quality gain is real; parallel execution makes latency cost zero |
| Orchestration | Async functions | **LangGraph state machine** | Cleaner state, easier debugging at scale, judges expect it |
| Observability | Hand-rolled trace panel | **Langfuse (self-hosted)** | Production-grade tracing, free, OpenTelemetry-compatible |
| Bug memory | Cut (empty on day 1) | **ChromaDB-backed, persistent across sessions** | Compounds value over time; starts empty but improves continuously |
| Language depth | 2 deep (Python, JS), 8 shallow | **6 deep (Py, JS, TS, Java, Go, Rust), 9 partial, 100+ via tree-sitter** | Real coverage, not just claims |
| Evaluation | One-shot golden dataset | **Continuous eval pipeline + 200+ golden cases** | Long-term quality assurance |
| UX scope | Streamlit pivot to React | **React + Tailwind from day 1, with diff viewer, syntax highlighting, agent timeline** | Polish matters when there's no excuse |

**Decisions that did NOT change (still right):**
- 4 → 5 agents (with parallel execution, the 5th is free in wall-clock terms)
- Multi-model right-sizing (8B + 32B; 70B not needed)
- Hardened Docker sandbox (security non-negotiable)
- Diff-based security regression (still the unique differentiator)
- Groq primary + Ollama fallback (still the resilience play)
- Fast-path bypass for simple inputs (still saves ~2s when applicable)
- Streaming Explainer (still the perceived-latency win)
- Fail-fast then parallel validators (still saves 4s)

---

## 1. The Final Component Roster

**5 LLM agents · 6 deterministic tools · 1 hardened sandbox.**

The 5th agent (Critic) earns its slot because it runs **in parallel with the Explainer**, so its latency contribution is zero on the happy path. We don't add agents that aren't free.

```
                          USER INPUT
              (snippet ± error ± failing test ± screenshot)
                              │
                              ▼
              ┌──────────────────────────────────┐
              │  TOOL 1: SMART INPUT HANDLER     │   deterministic
              │  • Language detection             │
              │  • Auto-execute if no error       │
              │  • Multi-modal: text or image     │
              │  • Fast-path classifier            │
              └─────────────┬────────────────────┘
                            │ ~0.2s
                            ▼
              ┌──────────────────────────────────┐
              │  TOOL 2: CONTEXT BUILDER         │   deterministic
              │  Three subtasks in parallel:      │
              │  • Execution tracer (in sandbox)  │
              │  • Call graph (tree-sitter)       │
              │  • AST extraction                 │
              │  • Bug memory similarity search    │
              └─────────────┬────────────────────┘
                            │ ~1.0s
                            ▼
              ┌──────────────────────────────────┐
              │  AGENT 1: DIAGNOSER              │   LLM #1, 8B model
              │  • 3 ranked hypotheses            │
              │  • Auto-generated failing test    │
              │  • Root cause analysis            │
              │  • Affected scope classification  │
              └─────────────┬────────────────────┘
                            │ ~1.0s
                            ▼
              ┌──────────────────────────────────┐
              │  AGENT 2: PATCHER                │   LLM #2, 32B coder
              │  • Generate minimal unified diff  │
              │  • Must pass generated test       │
              │  • Safety constraints active      │
              │  • Past similar fix injected      │
              └─────────────┬────────────────────┘
                            │ ~1.9s
                            ▼
        ┌─────────────────────────────────────────────┐
        │  TOOL 3: VALIDATOR                          │   deterministic
        │                                             │
        │  Gate 1: SYNTAX (tree-sitter) ─────── ~0.1s │
        │  └── fail-fast: skip rest if broken         │
        │                                             │
        │  Gates 2-4 IN PARALLEL ────────────── ~3.0s │
        │  ├── Gate 2: TYPE CHECK                     │
        │  ├── Gate 3: SECURITY (Bandit + Semgrep)    │
        │  └── Gate 4: TESTS (sandboxed)              │
        │                                             │
        │  Gate 5: DIFF REGRESSION ─────────── ~0.3s  │
        │  └── reject if new vulnerabilities added    │
        └────────┬───────────────────────┬────────────┘
                 │ PASS                  │ FAIL
                 │                       │
                 │           ┌───────────▼───────────┐
                 │           │  AGENT 5: REFLECTOR   │   LLM #5, 8B
                 │           │  (conditional)        │   ~0.6s
                 │           │  • Decide: refine H1  │
                 │           │    or escalate to H2  │
                 │           │  • Structured retry   │
                 │           │    constraints        │
                 │           └───────────┬───────────┘
                 │                       │
                 │            (loops to Patcher, max 2 retries)
                 │
                 ▼
        ┌────────────────────┬─────────────────────────┐
        │ PARALLEL DUET (zero added latency)            │
        │                                               │
        │  ┌─────────────────┐  ┌──────────────────┐   │
        │  │ AGENT 3: CRITIC │  │ AGENT 4: EXPLAINER│   │
        │  │ LLM #3, 8B      │  │ LLM #4, 8B, stream│   │
        │  │ ~0.7s           │  │ ~1.1s             │   │
        │  │                 │  │                   │   │
        │  │ • Score 0-10    │  │ • Reasoning trace │   │
        │  │ • Verdict       │  │ • Semantic diff   │   │
        │  │ • Safety review │  │ • Downstream impact│   │
        │  └─────────────────┘  └──────────────────┘   │
        │  If Critic rejects → kill stream → Reflector  │
        │  If Critic accepts → Explainer already done   │
        └─────────────────────┬─────────────────────────┘
                              │ max(0.7, 1.1) = 1.1s
                              ▼
              ┌──────────────────────────────────┐
              │  STREAMING REACT UI               │
              │  • Diff view + syntax highlight   │
              │  • Reasoning panel                │
              │  • Test results                   │
              │  • Safety trace (5-layer)         │
              │  • Agent timeline (Langfuse)      │
              │  • Apply / Reject / PR buttons    │
              └──────────────────────────────────┘

   HAPPY PATH P50:    ~9 seconds wall-clock, ~8s perceived
   WITH REFLECTOR:    ~15 seconds (retry adds 5.5s)
   FAST PATH:         ~5 seconds (skips Diagnoser when error is clear)
```

---

## 2. The 5 Agents — Detailed Specification

### 2.1 Agent 1 — Diagnoser

**Role:** Generate 3 ranked hypotheses about the root cause, write a failing test that proves the bug, and identify the affected scope (local function, caller, callee, cross-file). Single structured LLM call.

**Why this agent exists:**
- Hypothesis-driven diagnosis beats single-guess: when retries are needed, the next hypothesis is *different*, not a blind reformulation
- Test generation is a permanent regression artifact — the bug can never silently come back
- One LLM call produces both outputs (hypotheses + test) since they share the same context — no latency penalty for combining

**Why not split into Diagnoser + TestGen:**
- Same context, same reasoning. Splitting costs 1.5s for no quality gain.

**Why not merged with Patcher:**
- Patcher needs a 32B code-specialized model. Diagnoser only needs structured classification. Different optimal models = different agents.

**Model:** Llama 3.1 8B Instant on Groq
**Wall-clock:** ~1.0s (500-token output at 750 tok/s + 300ms TTFT)
**Temperature:** 0.2 (some diversity in hypotheses, mostly deterministic)
**Token budget:** 3000 in / 600 out

**Output schema:**
```python
class DiagnoserOutput(BaseModel):
    root_cause: str
    affected_scope: Literal["local", "caller", "callee", "cross_file", "ambient"]
    hypotheses: list[Hypothesis]   # exactly 3, ranked by confidence
    generated_test: str             # idiomatic test for the detected language
    test_assertion_summary: str     # one-liner explaining what the test proves
    requires_clarification: bool
    clarification_question: str | None

class Hypothesis(BaseModel):
    theory: str
    evidence: list[str]             # specific lines from trace + AST
    confidence: float               # 0.0-1.0
    fix_direction: str              # one sentence
    risk_if_wrong: str              # what could break if we apply this fix incorrectly
```

### 2.2 Agent 2 — Patcher

**Role:** Take the top hypothesis + the generated failing test + safety constraints + similar past fix from bug memory, produce a minimal unified diff.

**Why this agent exists:**
- Code generation is fundamentally different from classification — needs a code-specialized model
- The "must pass this test" constraint dramatically improves correctness vs unconstrained generation
- The past-fix-from-memory injection turns experience into measurable quality gains over time

**Why not 70B model:**
- Qwen 2.5 Coder 32B outperforms Llama 3.3 70B on HumanEval, MBPP, and SWE-bench. Code-specialized < general-purpose, even when general is bigger. And it's faster.

**Model:** Qwen 2.5 Coder 32B on Groq (backup: qwen2.5-coder:14b on Ollama)
**Wall-clock:** ~1.9s (400-token output at 250 tok/s + 300ms TTFT)
**Temperature:** 0.1 (we want determinism for bug fixes)
**Token budget:** 4500 in / 800 out

**Output schema:**
```python
class PatcherOutput(BaseModel):
    unified_diff: str
    confidence: float
    lines_changed: int                       # flag if > 15
    approach: str                            # one sentence
    hypothesis_used: str                     # H1, H2, or H3
    potential_side_effects: list[str]
    safety_constraints_respected: list[str]
    api_signature_preserved: bool            # hard rule
    new_imports_required: list[str]
    blocked_reason: str | None               # if cannot fix safely
    alternative_approach: str | None
```

### 2.3 Agent 3 — Critic (runs in parallel with Explainer)

**Role:** Score the patch against an anchored rubric, decide accept/regenerate/reject. Catches semantic issues the deterministic validator can't (missing authz, IDOR, business-logic violations).

**Why this agent exists:**
- Validator gates catch syntactic and known-pattern issues. Critic catches **semantic** issues — patches that pass tests + Bandit but are logically wrong.
- Running in **parallel with Explainer** makes the latency cost zero on the happy path.

**The parallel execution trick:**
```python
async def post_validation():
    critic_task    = asyncio.create_task(critic_agent(patch, validation, original))
    explainer_task = asyncio.create_task(explainer_agent(patch, validation))
    
    # Wait for Critic first — it's faster (0.7s vs 1.1s)
    verdict = await critic_task
    
    if verdict.action == "reject":
        explainer_task.cancel()      # don't waste compute on rejected output
        return await reflect_and_retry(verdict)
    
    # Explainer is already running; user sees streaming output
    explanation = await explainer_task
    return finalize(patch, explanation, verdict)
```

**Why not deterministic rubric only:**
- Deterministic rubric catches: tests fail, syntax broken, security regressions, patch == original. ~70% of bad patches.
- LLM Critic catches: removed authz check, broke a callsite that wasn't tested, fixed the bug but in a non-idiomatic way that will confuse future readers. The remaining ~30%.
- With zero latency cost (parallel), there's no reason not to have both.

**Model:** Llama 3.1 8B Instant on Groq
**Wall-clock:** ~0.7s
**Temperature:** 0.0 (deterministic verdicts)
**Token budget:** 3500 in / 400 out

**Output schema:**
```python
class CriticVerdict(BaseModel):
    score: int                                # 0-10
    action: Literal["accept", "regenerate", "reject", "ask_user"]
    confidence: float
    safety_concerns: list[str]
    correctness_concerns: list[str]
    minimality_concerns: list[str]
    feedback_for_patcher: str | None          # if regenerate
    user_question: str | None                 # if ask_user
```

### 2.4 Agent 4 — Explainer (streams to UI in parallel with Critic)

**Role:** Generate three human-readable outputs in one structured call: reasoning trace, semantic diff, and downstream impact analysis. Streams to UI so user sees text immediately.

**Why this agent exists:**
- Judging criterion #3 is explicitly "reasoning trace (why this fix)"
- Three outputs from one LLM call is high value per token
- Runs after validation, so explanations are grounded in real results (cannot hallucinate test outcomes)
- Streaming makes perceived latency near-zero

**Why not merged with Critic:**
- Different audiences: Critic talks to the system (structured verdict), Explainer talks to the human (prose narrative)
- Different optimal prompts
- Parallel execution = zero combined latency cost

**Model:** Llama 3.1 8B Instant on Groq
**Wall-clock:** ~1.1s full / ~0.3s to first token (streamed)
**Temperature:** 0.3 (slight variation for natural prose)
**Token budget:** 3000 in / 800 out, streamed

**Output schema:**
```python
class ExplainerOutput(BaseModel):
    reasoning_trace: str             # why this bug existed, why this fix works
    semantic_diff: str               # plain-English what changed (behavior level)
    downstream_impact: list[Impact]  # callers/callees that may be affected
    apply_recommendation: Literal["safe", "review_recommended", "needs_human"]
    confidence_summary: str

class Impact(BaseModel):
    file: str
    line: int
    description: str
    severity: Literal["info", "warning", "critical"]
```

### 2.5 Agent 5 — Reflector (conditional only on validation failure)

**Role:** When the Validator rejects a patch, decide whether to **refine the current hypothesis** (e.g., fix the type mismatch without changing approach) or **escalate to the next hypothesis** (try theory H2 with completely different fix direction).

**Why this agent exists:**
- Blind retry wastes calls. Structured fallback converges faster.
- Zero cost on happy path (only fires when validation fails)
- The retry decision is itself a small reasoning problem worth dedicating a call to

**Why not merged with Critic:**
- Critic runs after validation passes. Reflector runs after validation fails. Mutually exclusive.

**Why not merged with the next Patcher invocation:**
- Cleaner separation of concerns; Reflector's decision becomes a *constraint* for Patcher, not mixed in with patch generation logic

**Model:** Llama 3.1 8B Instant on Groq
**Wall-clock:** ~0.6s (only paid on failure)
**Temperature:** 0.0
**Token budget:** 2500 in / 300 out

**Output schema:**
```python
class ReflectorDecision(BaseModel):
    strategy: Literal["refine_current", "escalate_h2", "escalate_h3", "give_up"]
    failure_root_cause: str                   # what really went wrong
    constraint_for_next_attempt: str          # do/don't list for Patcher
    confidence_in_strategy: float
    abandoning_hypothesis: str | None
    new_hypothesis_to_try: str | None
```

### 2.6 Why Exactly 5 — Not 4, Not 6, Not 7

We tested 4 through 7 agents conceptually. **5 is the maximum where adding another agent strictly increases quality.** Here's the reasoning per candidate:

| Considered agent | Verdict | Reason |
|---|---|---|
| Planner (separate from Diagnoser) | ❌ Cut | Adds 1s for what Diagnoser already classifies |
| Validator-as-Agent | ❌ Cut | Routing is deterministic; LLM adds nothing |
| TestGen-as-Agent | ❌ Cut | Merged into Diagnoser (same context, free) |
| Safety-Critic (separate) | ❌ Cut | 5-layer deterministic safety already comprehensive |
| Memory-Retriever-as-Agent | ❌ Cut | Vector lookup is a tool, not an agent |
| Orchestrator-as-Agent | ❌ Cut | LangGraph state machine is not an agent |
| **Diagnoser** | ✅ Keep | Classifies + ranks hypotheses + generates test |
| **Patcher** | ✅ Keep | Different model class (code 32B), different task |
| **Critic** | ✅ Keep | Parallel with Explainer = zero latency cost, catches semantic issues |
| **Explainer** | ✅ Keep | Maps to judging criterion #3 directly, streams |
| **Reflector** | ✅ Keep | Only runs on failure, structured retry is materially better than blind |

**Honest agent count: 5.** Every agent has a distinct prompt, distinct schema, distinct model assignment, and a distinct moment in the pipeline. None is theater.

---

## 3. The 6 Deterministic Tools

Tools execute logic, not reasoning. They produce structured outputs that agents consume. No LLM calls.

> **Note on AST pattern detection:** Custom AST-based pattern queries (formerly Tool 7) are now folded into Semgrep custom rule packs (`semgrep --config=./custom_rules.yml`) within Tool 3 (Validator). One fewer tool to maintain, same coverage, more battle-tested rule engine.

### Tool 1 — Smart Input Handler

Decides what kind of input we're dealing with and dispatches accordingly. This is the first thing user input touches — it normalizes diverse input modes into a single typed structure the rest of the pipeline can consume.

#### 1.1 The three input modes it handles

| Mode | What user provides | How handler responds |
|---|---|---|
| **A — Code + Error** | Snippet + traceback | Best case. Skip auto-execute. Try fast-path. |
| **B — Code only** | Snippet, says "fix this" | Run code in sandbox to discover the error. If no runtime error, run static analysis to discover **latent bugs**, then Fix pipeline runs on each discovered bug. |
| **C — File upload** | One or more `.py`/`.js`/etc. files | Same as A or B per file, plus multi-file context |

> **Note:** Screenshot/OCR input (Mode D) is deferred to v2. v1 accepts text only. See Section 12 (Roadmap).

> **Note on the scope:** Per the problem statement ("Build an agent that reads a repo snippet, **proposes fixes, generates patches, and explains reasoning**"), the system stays focused on bug-fixing. When the user provides no error, Mode B auto-discovers bugs via execution + static analysis — this is still bug-fixing, not code review.

#### 1.2 The dispatcher decision tree

```python
async def handle_input(raw: RawInput) -> NormalizedInput:
    # Step 1: Normalize input into text
    if raw.is_file_upload:
        raw.text = await read_files(raw.files)
        raw.is_multi_file = len(raw.files) > 1
    
    # Step 2: Detect language (cascading strategy)
    language = detect_language(raw.text, filename_hint=raw.filename)
    
    # Step 3: Extract or discover the error
    if raw.error_msg:
        error = parse_traceback(raw.error_msg, language)
    else:
        # User said "fix this" without error → try to find one
        error = await auto_execute_to_find_error(raw.text, language)
        if error is None:
            # Code ran without crashing → discover latent bugs via static analysis
            error = await discover_latent_bugs(raw.text, language)
    
    # Step 4: Detect repo-mode vs snippet-mode
    line_count = raw.text.count("\n")
    mode = (
        "repo"     if raw.is_multi_file or line_count > 300 else
        "file"     if line_count > 50 else
        "snippet"
    )
    
    # Step 5: Fast-path classifier
    fast_path_eligible = (
        error is not None and
        error.has_clear_location and
        line_count < 50 and
        not raw.is_multi_file and
        language in TIER_1_LANGUAGES
    )
    
    return NormalizedInput(
        code=raw.text,
        language=language,
        error=error,
        mode=mode,
        fast_path=fast_path_eligible,
        filename=raw.filename,
    )
```

#### 1.3 Language detection — the cascade

Multiple cheap checks fall through to more expensive ones. Stops at the first confident match:

```python
def detect_language(code: str, filename_hint: str | None) -> str:
    # 1. File extension (cheapest, most reliable when available)
    if filename_hint:
        for ext, lang in ADAPTERS_BY_EXTENSION.items():
            if filename_hint.endswith(ext):
                return lang
    
    # 2. Shebang line for scripts
    first_line = code.split("\n", 1)[0]
    if first_line.startswith("#!"):
        if "python" in first_line: return "python"
        if "node" in first_line: return "javascript"
        if "ruby" in first_line: return "ruby"
        if "/bash" in first_line or "/sh" in first_line: return "bash"
    
    # 3. tree-sitter try-each (cheap, high accuracy on real code)
    for candidate in ["python", "javascript", "typescript", "java",
                       "go", "rust", "ruby"]:
        if tree_sitter_parses_cleanly(code, candidate):
            return candidate
    
    # 4. LLM-based detection (slow, last resort)
    return llm_detect_language(code)   # ~1s, only when needed
    
    # 5. If nothing confident — DefaultAdapter handles it
    # (returned as "default", which never crashes)
```

The cascade typically stops at step 1 (file extension) or step 3 (tree-sitter). Step 4 is rarely reached.

#### 1.4 Auto-execute when no error is provided

This is the most important UX feature — users paste code and say "what's wrong" without giving an error. The handler runs the code in the sandbox to discover it:

```python
async def auto_execute_to_find_error(code: str, language: str) -> Error | None:
    adapter = get_adapter(language)
    
    # Run inside hardened Docker sandbox (same one used everywhere)
    result = await sandbox_pool.execute(
        language=language,
        code=code,
        cmd=adapter.run_command(),     # e.g. ["python", "main.py"]
        timeout=10
    )
    
    if result.exit_code == 0:
        # Code didn't crash — fall back to static analysis mode
        return await static_analysis_for_issues(code, language)
    
    # Parse the traceback
    return parse_traceback(result.stderr, language)
```

If the code runs without crashing, we fall into **static analysis mode**: run the security scanners and AST pattern matcher to find issues the user didn't ask about. This handles "review my code" requests.

#### 1.5 Fast-path mechanics

When the fast-path classifier returns true, we **bypass the Diagnoser entirely** and go straight to the Patcher with a synthesized hypothesis derived from the error:

```python
def synthesize_hypothesis_from_error(error: Error) -> Hypothesis:
    return Hypothesis(
        theory=f"{error.exception_type} at line {error.line}: {error.message}",
        evidence=[
            f"traceback shows {error.exception_type}",
            f"line {error.line}: {error.crash_line_text}"
        ],
        confidence=0.7,             # not as confident as a real diagnosis
        fix_direction=error.suggested_fix_direction(),
        risk_if_wrong="fast-path may miss subtle cross-function causes"
    )
```

**When fast-path runs:** ~7.7s total wall-clock (saves ~1.5s by skipping Diagnoser).
**When it doesn't:** full pipeline at ~8.7s.
**Trade-off:** fast-path skips hypothesis ranking, so retries on failure are limited to "regenerate" rather than "escalate to H2." If the first patch fails, we fall back to the full Diagnoser pipeline on retry.

#### 1.6 Output: the NormalizedInput

```python
class NormalizedInput(BaseModel):
    code: str
    language: str                       # never None — DefaultAdapter handles unknowns
    error: Error | None                 # populated either by user or auto-execute
    mode: Literal["snippet", "file", "repo"]
    fast_path: bool                     # skip Diagnoser?
    filename: str | None
    additional_files: list[FileRef] = [] # for multi-file mode

class Error(BaseModel):
    exception_type: str                 # "IndexError", "TypeError", etc.
    message: str
    line: int
    crash_line_text: str
    has_clear_location: bool
    raw_traceback: str
```

This typed object is what flows into the Context Builder.

### Tool 2 — Context Builder

The Context Builder is the **single highest-ROI component** in the system. It engineers a high-signal evidence package before any LLM token is generated. Quality of every downstream agent depends on quality of this package.

**Principle:** the LLM gets 150 lines of curated evidence, not 500 lines of raw code. Token reduction → faster inference + less hallucination + better focus.

#### 2.1 The four subtasks run in parallel

All four execute concurrently via `asyncio.gather`. Total wall-clock ≈ max(subtask times) ≈ 1.0s.

```python
async def build_context(input: NormalizedInput) -> ContextPackage:
    tracer_task    = asyncio.create_task(execution_tracer(input))
    callgraph_task = asyncio.create_task(call_graph_walker(input))
    ast_task       = asyncio.create_task(ast_extractor(input))
    memory_task    = asyncio.create_task(bug_memory_search(input))
    
    trace, callers_callees, ast_data, similar_fixes = await asyncio.gather(
        tracer_task, callgraph_task, ast_task, memory_task
    )
    
    return assemble_package(input, trace, callers_callees, ast_data, similar_fixes)
```

#### 2.2 Subtask A — Execution Tracer

Captures actual runtime variable values at each line, especially at the crash point. This is what gives the Diagnoser **observed truth** instead of speculation.

**Python implementation (Tier 1):**

```python
# tracer/python_tracer.py
TRACER_HARNESS = """
import sys, json, io, traceback

_TRACE = []

def _trace_fn(frame, event, arg):
    if event == "line":
        # Capture serializable locals only
        snap = {{}}
        for k, v in frame.f_locals.items():
            try:
                snap[k] = repr(v)[:200]   # cap each value at 200 chars
            except Exception:
                snap[k] = "<unrepresentable>"
        _TRACE.append({{
            "line": frame.f_lineno,
            "locals": snap
        }})
    return _trace_fn

sys.settrace(_trace_fn)
try:
{user_code_indented}
except Exception as e:
    _TRACE.append({{
        "crash": {{
            "type": type(e).__name__,
            "msg": str(e),
            "traceback": traceback.format_exc()
        }}
    }})
sys.settrace(None)
print("__TRACE_START__")
print(json.dumps(_TRACE))
print("__TRACE_END__")
"""

async def python_tracer(code: str) -> RuntimeTrace:
    indented = "\n".join("    " + line for line in code.split("\n"))
    harness = TRACER_HARNESS.format(user_code_indented=indented)
    
    # CRITICAL: tracer runs INSIDE the Docker sandbox, never on host
    result = await sandbox_pool.execute(
        language="python",
        code=harness,
        cmd=["python", "/workspace/traced.py"],
        timeout=10
    )
    
    return parse_trace_output(result.stdout)
```

**Why this is safe:** the harness runs inside the hardened Docker sandbox (`--network=none`, `--cap-drop=ALL`, etc.). Even malicious snippets cannot escape. This is the fix to the most common mistake in tracer designs.

**Other languages (Tier 1–3):**

| Language | Tracer mechanism | Variable capture? |
|---|---|---|
| Python | `sys.settrace` harness | ✅ full |
| Ruby | `TracePoint` API harness | ✅ full |
| JavaScript | `node --inspect-brk` + CDP client | ⚠️ top frame only |
| TypeScript | compile to JS → same as JS | ⚠️ top frame only |
| Java | parse stderr stack trace | ❌ exception type + line only |
| Go | parse panic output | ❌ exception type + line only |
| Any other | run + capture stderr | ❌ exit code + stderr only |

**Output schema:**
```python
class RuntimeTrace(BaseModel):
    tier: int                          # 1, 2, or 3
    lines: list[LineSnapshot]          # empty if tier 3
    crash: CrashEvent | None
    captured_variables: bool           # informs Diagnoser what evidence it has
    fallback_reason: str | None        # explains tier 3 degradation

class LineSnapshot(BaseModel):
    line_number: int
    locals: dict[str, str]             # variable_name → repr string
    branch_taken: str | None           # "if-true", "else", "loop-iter-3"
```

#### 2.3 Subtask B — Call Graph Walker

Uses tree-sitter to find functions that call the buggy function (callers) and functions the buggy function calls (callees). The Diagnoser uses this to decide if the bug is **local**, in the **caller**, or in the **callee**.

**The tree-sitter queries:**

```python
# Find all CALLERS of the target function
CALLERS_QUERY = """
(call
  function: [
    (identifier) @callee_name
    (attribute attribute: (identifier) @callee_name)
  ]
  (#eq? @callee_name "{target_function}")) @call_site
"""

# Find all CALLEES (function calls) inside the target function body
CALLEES_QUERY = """
(function_definition
  name: (identifier) @fn_name (#eq? @fn_name "{target_function}")
  body: (block
    (expression_statement
      (call function: (identifier) @called) @callee_site)))
"""

async def call_graph_walker(input: NormalizedInput) -> CallGraphContext:
    target = extract_buggy_function_name(input)  # from error line
    
    tree = tree_sitter_parse(input.code, input.language)
    
    callers = run_query(tree, CALLERS_QUERY.format(target_function=target))[:3]
    callees = run_query(tree, CALLEES_QUERY.format(target_function=target))[:2]
    
    return CallGraphContext(
        callers=[extract_signature(c) for c in callers],
        callees=[extract_signature(c) for c in callees],
        target_function=target
    )
```

**What gets extracted (signatures only, not bodies):**

```python
# Example output
callers = [
    FunctionSignature(
        name="main",
        signature="def main():",
        call_line="result = process(user_input)",
        line_number=12
    ),
    FunctionSignature(
        name="handle_request",
        signature="def handle_request(req: Request) -> Response:",
        call_line="data = process(req.body)",
        line_number=47
    ),
]

callees = [
    FunctionSignature(
        name="transform",
        signature="def transform(data: list) -> list:",
        body_summary="returns [x * 2 for x in data]"
    ),
]
```

**Why signatures, not full bodies:** keeps the context package lean. A 500-line repo passes through this and yields ~30 lines of relevant signature context, not the full file. Token efficiency is critical for both latency and accuracy.

**Multi-file mode:** when input.mode == "repo", the walker scans every uploaded file's AST and resolves call sites across files. This is how cross-file bugs get diagnosed.

#### 2.4 Subtask C — AST Extractor

Extracts the **exact buggy region** plus context-relevant surroundings. Not the whole file.

```python
async def ast_extractor(input: NormalizedInput) -> AstContext:
    tree = tree_sitter_parse(input.code, input.language)
    
    # Locate the error line in the AST
    error_node = find_node_at_line(tree, input.error.line)
    
    # Walk upward until we find the containing function
    function_node = find_enclosing_function(error_node)
    
    # Extract three things:
    return AstContext(
        # 1. The exact crashing expression (e.g. "result[0]")
        error_expression=error_node.text.decode(),
        
        # 2. 10 lines around the error point (5 before, 5 after)
        error_region=extract_lines(
            input.code,
            center=input.error.line,
            radius=5
        ),
        
        # 3. The full signature of the containing function
        function_signature=extract_signature(function_node),
        
        # 4. Imports at file top (to know what's available without the LLM guessing)
        imports=extract_imports(tree),
        
        # 5. Class context if function is a method
        class_context=find_enclosing_class(function_node),
    )
```

**Why these specific items:**
- `error_expression`: tells the Diagnoser the *exact* operation that failed (subscript, attribute access, function call). Narrows hypothesis space.
- `error_region`: surrounding lines for syntactic context — the LLM needs to see what variables were just assigned before the crash.
- `function_signature`: tells the Patcher the function's contract (parameter types, return type). The Patcher must not break this signature.
- `imports`: prevents the LLM from suggesting "import X" when X is already imported.
- `class_context`: if the buggy function is a method, the LLM needs to know about `self` attributes.

#### 2.5 Subtask D — Bug Memory Search

Queries ChromaDB for similar past bugs that were successfully fixed. The returned examples are injected into the Diagnoser's prompt as few-shot examples.

**The fingerprinting algorithm:**

```python
def bug_fingerprint(input: NormalizedInput) -> str:
    """
    Build a string that captures the bug's structural identity.
    Two bugs with the same fingerprint pattern are likely solvable
    by the same fix strategy.
    """
    components = [
        # Most specific signal
        f"error:{input.error.exception_type}",
        
        # The crashing operation type (subscript, attribute, call, etc.)
        f"op:{classify_error_operation(input.error.crash_line_text)}",
        
        # Function pattern (e.g. "list_access_after_transform")
        f"pattern:{infer_function_pattern(input)}",
        
        # Language (don't mix Python and JS fixes)
        f"lang:{input.language}",
    ]
    return " | ".join(components)


async def bug_memory_search(input: NormalizedInput) -> list[FixExample]:
    fingerprint = bug_fingerprint(input)
    
    # Embed the fingerprint + the buggy code region
    query_text = f"{fingerprint}\n\n{input.error.crash_line_text}"
    query_embedding = embed(query_text)
    
    # Search ChromaDB with language filter to avoid cross-contamination
    results = await bug_memory.query(
        embedding=query_embedding,
        n_results=2,
        filter={
            "language": input.language,
            "user_accepted": True,        # only fixes user kept
            "similarity_threshold": 0.75
        }
    )
    
    return [
        FixExample(
            original_code=r.original,
            fixed_code=r.patched,
            hypothesis=r.hypothesis,
            fix_pattern=r.fix_summary,
            confidence_in_pattern=r.success_rate,
        )
        for r in results
    ]
```

**Day 1 behavior:** memory is empty, returns `[]`. The Diagnoser has zero few-shot examples but still works using the other 3 subtasks' outputs.

**After 30 days of usage:** memory has ~100 fixes per common pattern. Bug memory becomes the **largest single quality booster** because past fixes are real evidence of what worked, not speculation.

**Why this won't backfire on bad fixes:**
- Only fixes where `user_accepted=True` enter memory
- A retention policy periodically re-validates stored fixes against the golden dataset
- The Critic agent can flag when a retrieved past fix conflicts with current evidence

#### 2.6 The assembled ContextPackage

After all four subtasks complete, they're merged into one typed object:

```python
class ContextPackage(BaseModel):
    # From AST Extractor
    error_node: str
    error_region: str                  # 10 lines around the bug
    function_signature: str
    imports: list[str]
    class_context: str | None
    
    # From Execution Tracer
    runtime_trace: RuntimeTrace
    
    # From Call Graph Walker
    callers: list[FunctionSignature]   # up to 3
    callees: list[FunctionSignature]   # up to 2
    
    # From Bug Memory Search
    similar_past_fixes: list[FixExample]  # 0 to 2
    
    # Meta
    language: str
    file_path: str | None
    mode: Literal["snippet", "file", "repo"]
    coding_constraints: list[str]      # "don't change public API", etc.
    tier_degradation: list[str]        # explicit notes about what's missing
```

**Token economics:** a naive approach dumps the entire file (~500 lines, ~6000 tokens). Our package is ~150 lines (~1800 tokens). **70% token reduction** with **higher signal-to-noise ratio.** Both faster and more accurate.

#### 2.7 Concrete example — what the package actually looks like

Input:
```python
def transform(data):
    return [x * 2 for x in data]

def process(items):
    result = transform(items)
    return result[0]

process([])  # IndexError: list index out of range
```

ContextPackage output (abbreviated):
```yaml
error_node: "return result[0]"
error_region: |
  def process(items):
      result = transform(items)
      return result[0]    # ← crash here
function_signature: "def process(items):"
imports: []
class_context: null

runtime_trace:
  tier: 1
  lines:
    - {line: 4, locals: {items: "[]"}}
    - {line: 5, locals: {items: "[]", data: "[]", result: "[]"}}
  crash:
    type: "IndexError"
    msg: "list index out of range"
    line: 6
  captured_variables: true

callers:
  - {name: "<module>", call_line: "process([])", line_number: 8}
callees:
  - {name: "transform", signature: "def transform(data):",
     body_summary: "returns [x * 2 for x in data]"}

similar_past_fixes:
  - {fix_pattern: "add empty-input guard before subscript access",
     confidence_in_pattern: 0.91,
     original_snippet: "...", fixed_snippet: "..."}

language: "python"
mode: "snippet"
coding_constraints:
  - "cannot change public API of process()"
  - "function name 'transform' implies always-produces-output (verify)"
tier_degradation: []
```

This is what flows into the Diagnoser. **150 lines of high-signal evidence**, with every field load-bearing. No noise, no speculation, no token waste.

#### 2.8 Graceful degradation for Tier-3 languages

For languages without runtime tracers (e.g. Java, Go), the Context Builder marks degradation explicitly:

```yaml
runtime_trace:
  tier: 3
  lines: []
  crash: {type: "NullPointerException", line: 42}
  captured_variables: false
  fallback_reason: "Java tracer unavailable — only stack trace parsed"

tier_degradation:
  - "No runtime variable values (Java is Tier 3 for tracer)"
  - "Diagnoser will speculate about variable state based on AST + stack only"
```

The Diagnoser's prompt reads `captured_variables: false` and adjusts its reasoning: it must speculate carefully, lower its confidence, and rely more on AST + call graph evidence.

**This honesty is what makes the system trustworthy.** It never pretends to have evidence it doesn't have.

### Tool 3 — Validator

Runs all 5 gates with **fail-fast + parallel** optimization:

```
Gate 1: SYNTAX (tree-sitter, 0.1s)
    └── if broken → return immediately, save 3s of sandbox time

Gates 2-4 in parallel via asyncio.gather (~3.0s wall-clock):
    ├── Gate 2: TYPE CHECK
    │     • Python: mypy
    │     • TypeScript: tsc --noEmit
    │     • Java: javac with --enable-preview
    │     • Go: go vet + staticcheck
    │     • Rust: cargo check
    │     • Others: skip with warning
    │
    ├── Gate 3: SECURITY (parallel within gate)
    │     • Bandit (Python)
    │     • Semgrep with --config=p/security-audit (universal)
    │     • ESLint security plugin (JS/TS)
    │     • gosec (Go)
    │     • SpotBugs (Java)
    │     • cargo-audit (Rust)
    │
    └── Gate 4: TESTS
          • Auto-generated test (from Diagnoser) MUST pass
          • Existing tests (if provided) — track delta from baseline

Gate 5: DIFF REGRESSION (0.3s)
    • Compare security scan of original vs patched code
    • Reject if patched introduces new HIGH/MEDIUM findings
    • Highlight when patch FIXES previously-existing vulnerabilities
```

**Output:**
```python
class ValidatorReport(BaseModel):
    overall_passed: bool
    gate_results: dict[str, GateResult]
    safety_diff: SafetyDiff           # introduced + fixed findings
    summary: str                      # one-line for Critic + Explainer
    detailed_failures: list[str]      # for Reflector if failed
```

### Tool 4 — Sandbox (the chokepoint)

**Every code execution funnels through this**, including the execution tracer, all validation gates, and any user-code invocation. See [Section 5](#5-sandboxing--isolation) for full spec.

### Tool 5 — Bug Memory (ChromaDB)

Persistent across sessions. **Stores every successfully-applied fix.**

**On store:**
```python
bug_memory.add(
    fingerprint={
        "error_type": "IndexError",
        "function_pattern": "list_access_after_transform",
        "language": "python",
    },
    successful_fix={
        "original": original_code,
        "patched": patched_code,
        "hypothesis": "empty list guard in transform()",
        "user_accepted": True,
        "timestamp": now,
    },
    embedding=embed(error_type + function_pattern + summary),
)
```

**On query:**
```python
similar = bug_memory.query(
    embedding=embed(current_fingerprint),
    n_results=2,
    filter={"language": current_language}
)
```

**Long-term value:** as the system handles more bugs, its diagnostic quality compounds. Day 1: empty, no benefit. Day 30: ~100 similar fixes per hypothesis. Day 90: bug memory is the single biggest quality driver.

### Tool 6 — Diff Regression Checker

Standalone deterministic check that powers Gate 5. Compares security scanner output before/after patch:

```python
def diff_regression(original_findings, patched_findings) -> SafetyDiff:
    orig = {(f.rule, f.severity) for f in original_findings}
    new  = {(f.rule, f.severity) for f in patched_findings}
    
    return SafetyDiff(
        introduced=list(new - orig),     # patch added new vulnerabilities
        fixed=list(orig - new),          # patch resolved vulnerabilities
        unchanged=list(orig & new),      # pre-existing, not caused by patch
        verdict=(
            "improvement"   if (new - orig) == set() and (orig - new) else
            "neutral"       if (new - orig) == set() else
            "regression"    if (new - orig) and not (orig - new) else
            "tradeoff"
        )
    )
```

**Why it's a separate tool:** the Critic and the Validator both consume its output. Centralized so the logic isn't duplicated.

---

## 4. Sandboxing & Isolation

Same as the hackathon architecture's sandbox, but with **production-grade additions** enabled by unlimited build time.

### 4.1 Per-Execution Hardening

```python
docker_args = [
    "docker", "run",
    "--rm",
    "--network=none",
    "--read-only",
    "--tmpfs=/tmp:size=64m,exec",
    "--tmpfs=/workspace-write:size=128m,exec",
    "--memory=512m",
    "--memory-swap=512m",
    "--cpus=1.0",
    "--pids-limit=64",
    "--security-opt=no-new-privileges",
    "--cap-drop=ALL",
    "--user=1000:1000",
    "--ulimit=nofile=64:64",
    "--ulimit=nproc=32:32",
    f"-v={tmp_path}:/workspace:ro",
    "-w=/workspace",
    f"debug-agent-sandbox-{language}",
    *cmd
]
```

### 4.2 Pre-Warmed Container Pool

Keep N pre-warmed containers per language running. Use `docker exec` for actual execution instead of `docker run`. Saves ~1s per execution.

```python
class SandboxPool:
    def __init__(self):
        self.pools = {
            "python":     PrewarmedPool("debug-agent-sandbox-python", size=3),
            "javascript": PrewarmedPool("debug-agent-sandbox-node", size=3),
            "java":       PrewarmedPool("debug-agent-sandbox-java", size=2),
            "go":         PrewarmedPool("debug-agent-sandbox-go", size=2),
            "multi":      PrewarmedPool("debug-agent-sandbox-multi", size=1),
        }
    
    async def execute(self, language, code, cmd, timeout=20):
        pool = self.pools.get(language, self.pools["multi"])
        container = await pool.acquire()
        try:
            return await container.exec(code, cmd, timeout)
        finally:
            await container.reset()       # clean filesystem
            await pool.release(container)
```

### 4.3 gVisor Integration (production optional)

For environments handling truly untrusted code at scale (multi-tenant SaaS), wrap Docker with gVisor (`--runtime=runsc`). Adds ~50ms but provides kernel-level isolation against container escape exploits. Optional, off by default.

---

## 5. Multi-Model Strategy

| Agent | Primary (Groq) | Fallback (Ollama) | Latency | Why |
|---|---|---|---|---|
| Diagnoser | llama-3.1-8b-instant | llama3.1:8b | ~1.0s | Classification + 3-way ranking. Speed > depth. |
| Patcher | qwen-2.5-coder-32b | qwen2.5-coder:14b | ~1.9s | Hardest task. Code-specialized. Beats Llama 70B on code. |
| Critic | llama-3.1-8b-instant | llama3.1:8b | ~0.7s | Scoring + verdict. Small model, parallel execution. |
| Explainer | llama-3.1-8b-instant | llama3.1:8b | ~1.1s | Synthesis of structured inputs. Prose generation. |
| Reflector | llama-3.1-8b-instant | llama3.1:8b | ~0.6s | Strategic retry decision. Small input/output. |

**Total models used: 2.** We could right-size further to 3 models (8B small, 32B code, 70B critic) but the marginal quality gain on Critic from 8B → 70B is dwarfed by the latency hit. **8B is the right call for Critic when it runs in parallel.**

**Why Groq specifically:**
- Free tier with generous limits (~30 RPM at the time of writing)
- ~5x faster than other free providers
- OpenAI-compatible API — Ollama also exposes OpenAI-compatible API, so fallback is a `base_url` swap
- Pre-deployed Llama, Qwen, Mixtral — no model loading time

**Why Ollama fallback:**
- Demos cannot fail. If Groq rate-limits or WiFi dies, local Ollama takes over.
- Same OpenAI-compatible interface means zero code change between primary and fallback.
- 100% local: signals "air-gapped capable" to regulated-industry customers.

---

## 6. Language Support

With unlimited build time, the language support strategy upgrades from "Python + JavaScript depth, others fallback" to **6 deep tiers**.

### 6.1 Three-Tier Support Matrix

| Tier | Languages | What works | Effort to add a new language |
|---|---|---|---|
| **Tier 1 (Full Depth)** | Python, JavaScript, TypeScript, Java, Go, Rust | All 7 features: trace, syntax, type, security, tests, AI diagnosis, reasoning | ~1 week per language |
| **Tier 2 (Strong)** | Ruby, PHP, C, C++ | 5 of 7: syntax, security, tests, AI diagnosis, reasoning. No runtime tracer or partial. | ~3 days per language |
| **Tier 3 (Core)** | Any tree-sitter language (~100+, including C#, Kotlin, Swift, Scala, Dart, Lua, Elixir, Haskell, etc.) | 4 of 7: syntax (tree-sitter), security (Semgrep auto), AI diagnosis, reasoning | Zero — the DefaultAdapter handles it |

> **Honest scoping:** Earlier drafts included Kotlin, Swift, Scala, Dart, and C# in Tier 2. After realistic maintenance costing, we restricted Tier 2 to the 4 languages we can reliably keep working across releases. The dropped languages still get full Tier-3 support via DefaultAdapter (AI diagnosis + patching + sandboxed execution + tree-sitter parsing + Semgrep scanning) — they just don't get a dedicated native scanner or test-runner adapter. Promotion to Tier 2 happens when a real user request justifies the maintenance commitment.

### 6.2 The Adapter Interface

```python
class LanguageAdapter(Protocol):
    name: str
    tier: int
    file_extensions: list[str]
    sandbox_image: str
    
    async def syntax_check(self, code: str) -> ToolResult: ...
    async def type_check(self, code: str) -> ToolResult | None: ...
    async def security_scan(self, code: str) -> ToolResult: ...
    async def runtime_trace(self, code: str) -> RuntimeTrace | None: ...
    async def run_tests(self, code: str, tests: str) -> TestResult: ...
    def language_specific_prompt_hints(self) -> str: ...
```

**The DefaultAdapter** ensures any unknown language gets at least:
- Tree-sitter syntax check (100+ grammars)
- Semgrep security scan (auto-config)
- AI-powered diagnosis (LLMs know dozens of languages)
- Sandboxed execution + stderr parsing

**The system never returns "language not supported."**

### 6.3 Honest Language Matrix (slide-ready)

| Feature | Py | JS/TS | Java | Go | Rust | Ruby | PHP | C# | C/C++ | Others |
|---|---|---|---|---|---|---|---|---|---|---|
| AI Diagnosis | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| AI Patching | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Syntax Check | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Type Check | mypy | tsc | javac | go vet | rustc | — | — | roslyn | clang -Wall | — |
| Security | Bandit+Semgrep | ESLint+Semgrep | SpotBugs+Semgrep | gosec+Semgrep | cargo-audit+Semgrep | rubocop+Semgrep | Semgrep | Semgrep | Semgrep | Semgrep* |
| Test Runner | pytest | jest | JUnit | go test | cargo test | rspec | phpunit | NUnit | ctest | — |
| Runtime Trace | ✅ sys.settrace | ⚠️ stack | ⚠️ stack | ⚠️ panic | ⚠️ panic | ✅ TracePoint | ⚠️ Xdebug | ⚠️ stack | ⚠️ stack | — |

\*Semgrep when rules exist for the language.

---

## 7. Tech Stack — Final

```
ORCHESTRATION
  Framework:        FastAPI + LangGraph
  State:            LangGraph state machine (typed Pydantic models)
  Async:            asyncio for all I/O and parallel agent execution
  HTTP:             httpx for outbound calls (HTTP/2 enabled)

LLM LAYER
  Primary API:      Groq (Llama 3.1 8B Instant, Qwen 2.5 Coder 32B)
  Local Fallback:   Ollama (llama3.1:8b, qwen2.5-coder:14b)
  Auth:             OpenAI-compatible API via base_url swap

EMBEDDINGS & MEMORY
  Embeddings:       sentence-transformers (all-MiniLM-L6-v2, 384-dim, 80MB)
  Vector DB:        ChromaDB (persistent, file-backed)
  Repo retrieval:   FAISS in-memory (for multi-file mode only)

DETERMINISTIC TOOLING
  AST:              tree-sitter + py-tree-sitter-languages (100+ grammars)
  Tracing:          sys.settrace (Python), TracePoint (Ruby), generic stderr parser
  Type checkers:    mypy, tsc, javac, go vet + staticcheck, cargo check
  Security:         Bandit, Semgrep (universal), ESLint, gosec, SpotBugs, cargo-audit, rubocop
  Test runners:     pytest, jest, JUnit, go test, cargo test, rspec, phpunit, nunit

SANDBOXING
  Container:        Docker (network=none, cap-drop=ALL, read-only, non-root, pids=64)
  Pool:             Pre-warmed containers per language (size 1-3)
  Optional:         gVisor runtime for kernel-level isolation in multi-tenant deploys

OBSERVABILITY
  Tracing:          Langfuse (self-hosted)
  Metrics:          Prometheus-compatible /metrics endpoint
  Logs:             Structured JSON to stdout (pluggable to Loki/Datadog)
  UI trace:         Live agent timeline panel in React

FRONTEND
  Framework:        React + Vite + Tailwind CSS
  Diff viewer:      react-diff-viewer-continued
  Syntax highlight: react-syntax-highlighter (Prism backend)
  WebSocket:        for streaming Explainer tokens
  State:            Zustand (lightweight, sufficient)

EVALUATION & QA
  Golden dataset:   200+ cases in JSON, organized by category + language
  Continuous eval:  GitHub Actions runs full dataset on every PR
  Regression detect: alerts if pass rate drops > 2%
  A/B testing:      prompt variants tracked with statistical significance

DEPLOYMENT
  Container image:  Multi-stage Docker build, ~600MB final
  Compose:          docker-compose.yml for local full-stack
  K8s:              Helm chart for production deployment
  CI/CD:            GitHub Actions for build + test + golden eval
```

---

## 8. End-to-End Pipeline & Latency Budget

### 8.1 Happy Path (no retry)

| Stage | Wall-clock | Cumulative | Perceived |
|---|---|---|---|
| Smart Input Handler | 0.2s | 0.2s | 0.2s |
| Context Builder (parallel) | 1.0s | 1.2s | 1.2s |
| Diagnoser (LLM #1) | 1.0s | 2.2s | 2.2s |
| Patcher (LLM #2) | 1.9s | 4.1s | 4.1s |
| Validator (syntax fail-fast → parallel) | 3.5s | 7.6s | 7.6s |
| Critic ∥ Explainer (parallel) | 1.1s (max) | 8.7s | **First Explainer token at ~7.9s** |
| **Total P50** | | **~8.7s** | **~8s perceived** |

### 8.2 With One Reflector Retry

| Stage | Wall-clock |
|---|---|
| (same up to Validator) | 7.6s |
| Validator fails | (covered above) |
| Reflector | 0.6s |
| Patcher (retry) | 1.9s |
| Validator (retry) | 3.5s |
| Critic ∥ Explainer | 1.1s |
| **Total P95** | **~14.7s** |

### 8.3 Fast Path (clear error, small snippet)

| Stage | Wall-clock |
|---|---|
| Smart Input Handler | 0.2s |
| Context Builder (parallel) | 1.0s |
| ~~Diagnoser~~ (skipped) | 0s |
| Patcher (with synthesized hypothesis from error) | 1.9s |
| Validator | 3.5s |
| Critic ∥ Explainer | 1.1s |
| **Total Fast Path** | **~7.7s** |

**Fast path triggers on ~30% of demo queries.**

### 8.4 Internal Fallback — Last-Resort Best-of-3

Not a user-facing mode. If both retry attempts (Reflector → Patcher) fail validation, the system runs 3 Patcher candidates in parallel on the 3rd attempt, picks the highest-scoring one. This is an internal escalation, not a documented feature. Adds ~2s only when both prior retries have already failed.

---

## 9. Security — The 4-Layer Defense

The architecture's security layers (originally 5, consolidated to 4 after merging AST patterns into Semgrep custom rules):

1. **Prompt-level blocklist** — Patcher system prompt forbids dangerous patterns
2. **Static scanners on patched code** — Bandit + Semgrep (with custom rule packs that include AST-level patterns) + language-specific scanners (see 9.1 below).
3. **Diff regression check** — compare original vs patched scan, reject if new vulnerabilities introduced
4. **Critic agent semantic review** — catches business-logic violations (authz, IDOR, TOCTOU) that static analysis cannot detect

All 4 layers feed into the Critic's final verdict. Patches that pass all 4 are shipped; failures loop to Reflector.

> **Note on the consolidation:** Earlier drafts had Layer 4 as a separate "AST Pattern Matcher" tool. Those patterns now live inside Semgrep custom rule packs (`semgrep --config=./custom_rules.yml`) which run in Layer 2. Same coverage, one fewer tool, more battle-tested rule engine.

### 9.1 Static Scanners — Additive, Not Replacements

**Important clarification:** Bandit and Semgrep from the hackathon architecture are **still core**. The final architecture **adds** language-native scanners alongside them, never instead of them. Layer 2 is now a *stack* of complementary scanners per language, not a single tool.

#### What runs per language (all scanners execute in parallel within Gate 3)

| Language | Scanners (run in parallel) | Why this combo |
|---|---|---|
| **Python** | Bandit + Semgrep | Bandit is the canonical Python security tool; Semgrep adds custom rule packs. Both layered = best Python coverage. |
| **JavaScript / TypeScript** | ESLint (security plugins) + Semgrep | ESLint has the deepest JS-specific rules (prototype pollution, unsafe DOM); Semgrep backs it up. |
| **Java** | SpotBugs + Semgrep | SpotBugs does JVM bytecode-level analysis (Log4Shell-class deserialization issues) that Semgrep cannot. |
| **Go** | gosec + Semgrep | gosec is the Go team's official security tool, catches Go-specific concurrency and pointer issues. |
| **Rust** | cargo-audit + Semgrep | cargo-audit checks dependencies against the Rust security advisory DB; Semgrep handles code patterns. |
| **Ruby** | rubocop (security cops) + Semgrep | rubocop catches Ruby idiomatic security issues and unsafe metaprogramming. |
| **PHP** | Semgrep (primary) | Semgrep has mature PHP rule packs; no widely-adopted PHP-native security scanner. |
| **C#** | SecurityCodeScan + Semgrep | SecurityCodeScan is the .NET-native tool. |
| **C / C++** | cppcheck + Semgrep | cppcheck catches memory-unsafe patterns Semgrep can't model. |
| **Any other language** | Semgrep with `--config=auto` | DefaultAdapter fallback — Semgrep auto-detects language and applies available rules. |

#### Why we layer instead of pick one

Each scanner has different strengths:
- **Bandit / gosec / SpotBugs** = deep language-specific rules curated by language community
- **Semgrep** = universal coverage + custom rule support + cross-language patterns
- **Native tools (ESLint, rubocop, cppcheck)** = idiomatic patterns native scanners miss

A patch must pass **all** scanners for its language. The diff regression check (Layer 3) operates on the **union** of all scanners' findings — if any scanner detects a new vulnerability the patch introduced, it's rejected.

#### Performance impact

All scanners for a given language run **concurrently in the sandbox** via `asyncio.gather`. Total Gate 3 wall-clock time = max(scanner latencies), typically ~1.5–2 seconds regardless of how many scanners apply. Adding scanners doesn't add latency — it adds coverage.

```python
async def security_gate(code: str, language: str) -> list[Finding]:
    scanners = SCANNERS_BY_LANGUAGE[language]   # e.g. [Bandit, Semgrep] for Python
    
    tasks = [asyncio.create_task(s.scan(code)) for s in scanners]
    all_findings = await asyncio.gather(*tasks)
    
    return deduplicate(flatten(all_findings))   # same issue from 2 scanners = 1 finding
```

#### Bottom line

**Nothing was replaced.** Bandit and Semgrep remain the foundation. The final architecture extends Layer 2 with native scanners per language to close coverage gaps. More scanners = stricter security gate = better protection, with no latency penalty thanks to parallel execution.

---

## 10. Production-Grade Additions (enabled by unlimited build time)

These are not optional polish — they're real features that elevate this from "demo project" to "deployable product."

### 10.1 Continuous Evaluation Pipeline

```yaml
# .github/workflows/eval.yml
name: Golden Dataset Evaluation
on:
  pull_request:
    paths: ['prompts/**', 'agents/**', 'tools/**']

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run full golden dataset
        run: python eval/run_all.py --output results.json
      - name: Compare to baseline
        run: python eval/compare.py results.json baseline.json
      - name: Fail if regression > 2%
        run: python eval/gate.py results.json baseline.json --max-regression 0.02
```

Every PR runs all 200 golden cases. Quality regressions block merge.

### 10.2 A/B Prompt Testing

```python
class PromptVariant(BaseModel):
    name: str
    template: str
    assignment_weight: float

class PromptManager:
    def get(self, agent_name: str, request_id: str) -> str:
        variants = self.variants[agent_name]
        variant = self.deterministic_assign(request_id, variants)
        return variant.template

    def record_outcome(self, request_id, variant_name, success_metrics):
        # Track which prompts produce better diagnoses, patches, etc.
        ...
```

Run multiple prompt variants in production, compare conversion / acceptance / patch-quality scores with statistical significance.

### 10.3 Multi-Modal Input

Accept inputs beyond raw text:
- **Pasted screenshots of error messages** → OCR via Tesseract or vision model → extracted text feeds Smart Input Handler
- **Stack trace screenshots from IDE** → same pipeline
- **Recorded terminal sessions** (asciinema) → extract last error
- **GIF/MP4 of bug reproduction** → frame-by-frame error extraction (v2)

### 10.4 IDE Integration

Build a VS Code extension that:
- Captures the active file's relevant section on demand
- Sends to the backend
- Renders the patch inline as a "code action" suggestion
- Shows the agent timeline in a side panel

Same backend, different frontend. No core architecture changes.

### 10.5 PR Creation

When the user clicks "Create PR" after accepting a patch:
- Branch is created via GitHub API
- Commit includes generated test as a regression test
- PR description is the Explainer's reasoning trace + semantic diff
- PR label is the Diagnoser's bug category

This connects the agent to the developer's actual workflow.

### 10.6 Confidence Calibration

Track every patch's `confidence` score against its actual outcome (accepted/rejected/edited/discarded by user). Recalibrate the model's self-reported confidence over time:

```python
# Post-deployment calibration
confidence_calibrator = IsotonicRegression()
confidence_calibrator.fit(
    X=raw_model_confidences,
    y=actual_acceptance_outcomes
)

# Then in production
calibrated_confidence = confidence_calibrator.transform(model_confidence)
```

UI shows the calibrated confidence, which means "85%" actually means "85% of the time, users accepted patches with this raw score."

### 10.7 Differential Testing

For high-stakes patches (security category): run the patched function against the **original function's outputs** on a wide range of inputs. Flag any behavioral divergence beyond what the patch should change.

```python
async def differential_test(original_fn, patched_fn, input_generator):
    divergences = []
    for inputs in input_generator(n=100):
        try:
            orig_out = await sandboxed_run(original_fn, inputs)
            patched_out = await sandboxed_run(patched_fn, inputs)
            if orig_out != patched_out:
                divergences.append((inputs, orig_out, patched_out))
        except Exception as e:
            # Patched should pass where original failed (the bug)
            ...
    return divergences
```

The Critic uses this output to confirm: "Behavior changed only in the failure case, all other inputs produce identical outputs." → high confidence.

### 10.8 Property-Based Testing (opt-in)

For numeric/algorithmic code, integrate Hypothesis (Python) or fast-check (JS) to generate hundreds of random inputs and verify properties hold:

```python
# After patch, run:
@given(st.lists(st.integers()))
def test_patch_property(data):
    result = patched_function(data)
    # Properties the Diagnoser inferred from the bug context
    assert isinstance(result, (list, int, type(None)))
    assert len(result) <= len(data) if isinstance(result, list) else True
```

Catches edge cases the user didn't test for. Latency cost: ~2 seconds, so opt-in only.

---

## 11. Observability — Langfuse Setup

Self-hosted Langfuse provides:
- **Per-request trace** showing every LLM call, every tool invocation, every agent transition
- **Latency breakdown** by stage
- **Token cost tracking** (real for paid, simulated for free Groq tier)
- **Error rate dashboards** per agent
- **Prompt version comparison** for A/B testing

Configuration:
```python
from langfuse import Langfuse
from langfuse.decorators import observe

langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host="http://localhost:3000"   # self-hosted
)

@observe()
async def diagnoser_agent(context: ContextPackage) -> DiagnoserOutput:
    # Automatically traced
    ...
```

In the React UI, show a real-time agent timeline reading from Langfuse:

```
Agent Timeline
─────────────────────────────────────────────────
12:00:00.000  ┌─ Smart Input Handler              ─ 0.2s
12:00:00.200  ├─ Context Builder (parallel)       ─ 1.0s
                ├── tracer: 0.4s
                ├── call_graph: 0.7s
                ├── ast: 0.5s
                └── bug_memory: 0.3s
12:00:01.200  ├─ Diagnoser (LLM #1)               ─ 1.0s
12:00:02.200  ├─ Patcher (LLM #2)                 ─ 1.9s
12:00:04.100  ├─ Validator (gates 2-4 parallel)   ─ 3.5s
12:00:07.600  ├─ Critic ∥ Explainer               ─ 1.1s
              │   ├── critic: 0.7s
              │   └── explainer: 1.1s (streamed)
12:00:08.700  └─ Done. Total: 8.7s
```

This visible timeline is judge candy. They can see the multi-agent claim being literally executed.

---

## 11.5 Efficiency Optimizations (Performance Wins)

Seven optimizations applied to bring P50 perceived latency from ~9s down to ~6s without sacrificing capability. Each is independently justifiable.

### 11.5.1 Token-Budget-Aware Compression (Repo Mode)

When users upload multi-file repos that exceed the model's context window, the Context Builder prunes intelligently rather than failing. Adapted from PR Agent's `pr_processing.py` algorithm:

```python
OUTPUT_BUFFER_TOKENS_SOFT_THRESHOLD = 1500
OUTPUT_BUFFER_TOKENS_HARD_THRESHOLD = 1000

def fit_to_budget(context: ContextPackage, model_max: int) -> ContextPackage:
    total = count_tokens(context)
    if total + OUTPUT_BUFFER_TOKENS_SOFT_THRESHOLD < model_max:
        return context  # fits, no pruning needed
    
    # Prune in priority order
    context = drop_low_priority_callers(context, budget_remaining)
    context = drop_imports_summary(context)
    context = compress_function_bodies(context)
    return context
```

**Impact:** Handles repo uploads gracefully. No OOM on large multi-file inputs.

### 11.5.2 Original-Code Scan Result Caching

The diff regression check scans both original and patched code. The original's scan doesn't change within a session, so we cache it:

```python
@functools.lru_cache(maxsize=64)
def scan_original_cached(code_hash: str, language: str) -> list[Finding]:
    return run_all_scanners(code_from_hash(code_hash), language)
```

**Impact:** Saves ~1.5s on every retry attempt. Up to 3s saved across 2 retries.

### 11.5.3 Per-Session Repo Embedding Index

When the user works on a multi-file project, the embedding index is built once per session and reused for all subsequent queries:

```python
class SessionRepoIndex:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.embeddings: faiss.IndexFlatL2 | None = None
        self.chunks: list[CodeChunk] = []
    
    async def ensure_built(self, files: list[File]):
        if self.embeddings is None:
            self.chunks = await chunk_repo(files)
            self.embeddings = await build_index(self.chunks)
```

**Impact:** First query pays indexing cost. Queries 2..N save ~2s each.

### 11.5.4 Streaming Patcher Tokens to UI

Previously only the Explainer streamed. The Patcher's ~1.9s LLM call now streams too — the user sees the diff appearing line-by-line as the LLM generates it:

```python
async def patcher_streaming(input: FixerInput) -> AsyncIterator[PatchDelta]:
    async for token in llm_client.stream(prompt):
        partial_yaml = accumulate(token)
        if hunk := try_parse_hunk(partial_yaml):
            yield PatchDelta(hunk=hunk)
```

**Impact:** Perceived latency drops from ~8s to ~5s. **The single biggest UX win.**

### 11.5.5 Validator Early-Success Short-Circuit

When the patch is small, bug memory has many identical past fixes, and no security regressions appear, the Critic LLM call is skipped:

```python
def can_short_circuit(validation, patch, bug_memory_hits) -> bool:
    return (
        validation.all_passed and
        patch.lines_changed < 5 and
        bug_memory_hits >= 5 and
        len(validation.safety_diff.introduced) == 0
    )
```

**Impact:** Saves ~0.7s on ~15% of queries. Trust the validator on high-confidence small patches.

### 11.5.6 Adaptive Per-Agent Timeouts

Hardcoded timeouts (15s Groq, 30s Ollama) waste budget on fast environments and starve slow ones. We track P95 actual latency per agent per backend, adapt timeouts to 1.5× rolling P95:

```python
class AdaptiveTimeout:
    def __init__(self, agent: str, backend: str):
        self.p95_history = deque(maxlen=100)
    
    def current_timeout(self) -> float:
        if len(self.p95_history) < 10:
            return DEFAULT_TIMEOUT
        return min(60.0, 1.5 * percentile(self.p95_history, 95))
```

**Impact:** Faster failure detection on healthy systems (~2s saved on retry fallback).

### 11.5.7 Smart Context Window Allocation

Instead of fixed per-agent token budgets, dynamically allocate based on actual context size and remaining budget:

```python
def allocate_context(remaining_budget: int) -> dict:
    if remaining_budget < 2000:
        return {"max_output_tokens": 400}  # tight
    elif remaining_budget < 4000:
        return {"max_output_tokens": 800}
    else:
        return {"max_output_tokens": 1500}  # generous
```

**Impact:** ~0.3s saved per query. Simpler patches finish faster, complex ones get more room.

### Cumulative Effect

| Optimization | Latency saved | Applies to |
|---|---|---|
| Token compression | (avoids failure) | Large repo uploads |
| Cache original scans | -1.5s | Retries (~30% of queries) |
| Repo session indexing | -2s | Queries 2..N in multi-query sessions |
| Stream Patcher | -3s perceived | Every query |
| Validator short-circuit | -0.7s | ~15% of queries |
| Adaptive timeouts | -2s average | Slow environments |
| Smart context allocation | -0.3s | Every query |

**P50 perceived latency: ~9s → ~6s.** Wall-clock P50: ~9s → ~7s.

---

## 12. Roadmap — v2 and Beyond

What we build first vs what comes later:

### v1 (current scope)
- 5 agents + 6 tools + sandbox
- 6 Tier-1 languages, 4 Tier-2, universal Tier-3 via DefaultAdapter
- Groq + Ollama fallback
- React UI with diff viewer + streaming Patcher + streaming Explainer
- ChromaDB bug memory (pre-seeded with golden dataset for demo)
- Langfuse observability
- 200-case golden dataset
- Continuous eval pipeline
- Token-budget-aware compression for repo mode
- Per-session repo embedding index
- Original-scan caching
- Validator short-circuit on high-confidence small patches

### v2 (3-6 months out)
- **Multi-modal input** (deferred from v1): screenshots of error messages, OCR via Tesseract / vision models, terminal recordings
- **Fine-tuned small models** for the Diagnoser (Qwen Coder fine-tuned on our bug-fix dataset)
- **IDE integrations**: VS Code, JetBrains, Vim/Neovim
- **PR creation flow** with GitHub/GitLab/Bitbucket support
- **Differential testing** auto-enabled for security patches
- **Property-based testing** as opt-in mode
- **Tier 2 → Tier 1 promotion** for Ruby, PHP (add full runtime tracers)
- **Tier 2 expansion**: add C#, Kotlin, Swift adapters when usage justifies maintenance
- **Team mode**: shared bug memory across team, role-based access

### v3 (6-12 months out)
- **Multi-repo context**: ingest a private repo, embed once, agent has whole-codebase awareness
- **Auto-fix on CI**: agent runs on every failing test in CI, proposes fix as PR comment
- **Active learning**: when users edit a proposed patch, learn from the edit
- **Speculative debugging**: run multiple hypothesis fixes in parallel, present the best
- **Cross-language fixes**: bug spans Python backend + TypeScript frontend, agent fixes both
- **Production debugging**: ingest logs + metrics, identify bug from production traces

---

## 13. What This Architecture Still Does NOT Do (Honest Limits)

Brutal honesty about gaps:

1. **It cannot fix bugs requiring deep domain knowledge.** If your bug is "this financial calculation is wrong because regulation 14.b changed last quarter," the agent has no way to know that. **Mitigation:** offer "low confidence — recommend human review" verdict.

2. **It cannot fix bugs that require runtime data we don't have.** A bug that only manifests under specific production load patterns isn't reproducible from a snippet. **Mitigation:** future repo-mode + log ingestion (v3).

3. **It cannot guarantee that its tests prove correctness.** Generated tests may be vacuous (`assert True`). **Mitigation:** mutation testing in v2 (verifies tests catch real bugs).

4. **It depends on LLM training distribution.** Patch quality on COBOL or Fortran is worse than on Python. **Mitigation:** surfaced confidence scores; honest tier matrix.

5. **It runs LLMs that can be jailbroken into outputting harmful patches.** Even with the safety blocklist. **Mitigation:** the 5-layer review catches most attempts; sandbox prevents host damage even if a malicious patch ships.

6. **Bug memory can degrade over time** if it accumulates bad fixes. **Mitigation:** retention policy + periodic re-evaluation of stored fixes against golden dataset.

7. **The Critic and Patcher use the same model class.** If 8B Llama has a blind spot, both agents may miss it. **Mitigation:** consider a different model family (e.g., Qwen for Patcher, Llama for Critic) — already done in v1.

These are real. Naming them in the pitch demonstrates engineering maturity.

---

## 14. Pitch Positioning

### The Headline (for slides + judge questions)

> **"Praman Setu: 5 agents, 7 tools, 1 hardened sandbox. ~9 seconds end-to-end. Runtime execution tracing inside a network-isolated container. Three ranked hypotheses with auto-generated failing test in one call. Parallel Critic + Explainer for zero-cost quality. Diff-based security regression detection. Persistent bug memory that compounds quality over time. Tier-1 support for 6 languages, universal fallback for 100+ via tree-sitter."**

### Why Each Phrase Matters to Judges

| Phrase | Judging signal |
|---|---|
| "5 agents, 7 tools, 1 sandbox" | Honest, specific count — not "many agents" theater |
| "~9 seconds end-to-end" | Demo-grade latency |
| "Runtime execution tracing inside a network-isolated container" | Both intelligence and security |
| "Three ranked hypotheses with auto-generated test" | Tree-of-thought + TDD in one call |
| "Parallel Critic + Explainer for zero-cost quality" | Latency-aware design |
| "Diff-based security regression detection" | The unique differentiator |
| "Persistent bug memory that compounds quality" | Long-term moat |
| "Tier-1 support for 6 languages, universal fallback for 100+" | Real coverage, honest depth |

### Anticipated Hostile Questions

**Q: "Why 5 agents when [other team] has 3?"**
A: We add an agent only when its quality contribution justifies its latency cost. The Critic runs in parallel with the Explainer, so its wall-clock cost is zero. The Reflector runs only on validation failure, so its happy-path cost is zero. Three of our five agents are conditional or parallel — we have the precision of 5 with the latency of 3.

**Q: "Why not LangChain?"**
A: LangChain's abstractions are designed for arbitrary tool-using chains. Our flow is fixed and well-understood: diagnose → patch → validate → critique+explain. LangGraph's typed state machine gives us better debuggability and observability for exactly this pattern. LangChain would add abstraction overhead without adding capability.

**Q: "How is this different from Cursor / GitHub Copilot?"**
A: Copilot suggests; we *prove*. Copilot generates code based on context. We generate code, run it in a hardened sandbox against a test we also generated, scan it for security regressions, and have a Critic LLM review it before showing the user. Copilot is a productivity multiplier for happy-path code writing. Praman Setu is a correctness-first tool for cases where wrong fixes are worse than no fix.

**Q: "Your bug memory starts empty. How is that valuable?"**
A: It's a compounding asset. Day 1, it provides zero value. Day 30, ~100 examples per common bug category meaningfully improve diagnosis. We frame this honestly: the system gets smarter the more you use it. For the demo, we pre-seed with 50 examples from our golden dataset.

**Q: "Can you really run the execution tracer safely?"**
A: Yes — and this is exactly where most implementations get it wrong. Our tracer runs inside the same hardened Docker sandbox as test execution: `--network=none`, `--read-only`, `--cap-drop=ALL`, non-root, with memory and PID limits. Even a malicious snippet that tries to exfiltrate environment variables cannot — there is no network. This is the design choice that separates "production-ready" from "demo only."

---

## 15. Repository Structure

```
debug-agent/
├── README.md
├── FINAL_ARCHITECTURE.md        # this document
├── pyproject.toml
├── docker-compose.yml
├── .env.example
│
├── backend/
│   ├── main.py                  # FastAPI app
│   ├── orchestrator/
│   │   ├── graph.py             # LangGraph state machine
│   │   ├── state.py             # Pydantic state types
│   │   └── routing.py
│   ├── agents/
│   │   ├── diagnoser.py
│   │   ├── patcher.py
│   │   ├── critic.py
│   │   ├── explainer.py
│   │   └── reflector.py
│   ├── tools/
│   │   ├── smart_input.py
│   │   ├── context_builder.py
│   │   ├── validator.py
│   │   ├── sandbox/
│   │   │   ├── pool.py
│   │   │   ├── executor.py
│   │   │   └── images/          # Dockerfiles per language
│   │   ├── bug_memory.py
│   │   ├── diff_regression.py
│   │   └── ast_patterns.py
│   ├── adapters/
│   │   ├── base.py
│   │   ├── python.py
│   │   ├── javascript.py
│   │   ├── typescript.py
│   │   ├── java.py
│   │   ├── go.py
│   │   ├── rust.py
│   │   ├── ruby.py
│   │   ├── php.py
│   │   ├── csharp.py
│   │   ├── c.py
│   │   ├── cpp.py
│   │   └── default.py
│   ├── llm/
│   │   ├── client.py            # Groq + Ollama unified client
│   │   ├── fallback.py
│   │   └── prompts/             # Jinja2 prompt templates
│   │       ├── diagnoser.j2
│   │       ├── patcher.j2
│   │       ├── critic.j2
│   │       ├── explainer.j2
│   │       └── reflector.j2
│   └── observability/
│       ├── langfuse_client.py
│       └── metrics.py
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── CodeInput.tsx
│   │   │   ├── DiffViewer.tsx
│   │   │   ├── ReasoningPanel.tsx
│   │   │   ├── TestResults.tsx
│   │   │   ├── SafetyTrace.tsx
│   │   │   └── AgentTimeline.tsx
│   │   ├── hooks/
│   │   │   └── useStreamingExplainer.ts
│   │   └── api/
│   │       └── client.ts
│   └── tailwind.config.js
│
├── evaluation/
│   ├── golden_dataset/
│   │   ├── python/              # 80 cases
│   │   ├── javascript/          # 50 cases
│   │   ├── java/                # 30 cases
│   │   ├── go/                  # 20 cases
│   │   └── multi/               # 20 cases
│   ├── run_all.py
│   ├── compare.py
│   └── baseline.json
│
├── infra/
│   ├── helm/                    # Kubernetes deployment
│   ├── docker/
│   │   ├── Dockerfile.backend
│   │   ├── Dockerfile.frontend
│   │   └── Dockerfile.sandbox-*  # one per language
│   └── monitoring/
│       └── prometheus.yml
│
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

---

## 16. Build Order (Not a Deadline, Just Sequence)

Without time pressure, the right build order is **incremental quality verification**:

1. **Foundation:** FastAPI scaffold + LangGraph state machine + Pydantic schemas + LLM client (Groq + Ollama) + sandbox base image
2. **First agent vertical (Python only):** Smart Input + Context Builder (Python tracer) + Diagnoser + Patcher → end-to-end "fix one Python bug" works
3. **Validation:** Validator with all 5 gates → patches now provably work
4. **Quality:** Critic + Reflector + retry loop → patches now consistently work
5. **UX:** Explainer + React UI with streaming → demos look professional
6. **Memory:** ChromaDB bug memory + similarity retrieval → compounding quality
7. **Languages:** JavaScript, TypeScript, Java, Go, Rust adapters → universal coverage
8. **Observability:** Langfuse + agent timeline UI + metrics → production-grade
9. **Evaluation:** 200-case golden dataset + continuous eval pipeline → quality protection
10. **Production-grade additions:** PR creation, IDE extension, multi-modal input, fine-tuning

**Each step delivers a working system. Each step is independently demoable.** No big-bang integration.

---

## 17. The Brutal Honesty Section

What this architecture does not promise:

- **It does not promise "all languages equally."** It promises tiered honesty. Python is best-in-class; Tier 3 languages are diagnosable but not deeply validated.
- **It does not promise zero hallucinations.** It promises 5 layers of detection so hallucinations are caught before shipping to the user.
- **It does not promise sub-second responses.** It promises ~9 seconds with rich context — faster than any LLM-only system can match while still being correct.
- **It does not promise immediate state-of-the-art on day 1.** Bug memory makes it better over weeks. Honest framing prevents over-claim.
- **It does not promise full autonomy.** Patches above a confidence threshold are auto-applied; below threshold are surfaced to the human. Trust is earned, not assumed.

These honest limits are themselves a competitive advantage. The team that claims everything works perfectly loses credibility. The team that says "here's exactly what works, here's where we degrade, here's why that's still better than competitors" wins technical-due-diligence rounds.

---

## 18. Final Decision Summary

| Question | Answer | Reasoning |
|---|---|---|
| How many LLM agents? | **5** (Diagnoser, Patcher, Critic, Explainer, Reflector) | Each justified individually; Critic and Reflector are parallel/conditional so contribute zero happy-path latency |
| How many deterministic tools? | **6** (Smart Input, Context Builder, Validator, Sandbox, Bug Memory, Diff Regression) | AST pattern queries consolidated into Semgrep custom rules within Validator |
| How many operating modes? | **3** (Fix Mode, Constrained Fix Mode, Run Mode) | Review Mode removed as off-spec; latent-bug discovery folded into Run Mode |
| Orchestration framework? | **LangGraph** | State machine fits the fixed agent flow; better debuggability than async functions when scaled |
| Primary LLM? | **Groq (Llama 3.1 8B + Qwen 2.5 Coder 32B)** | Fastest free inference; multi-model right-sizing |
| Backup LLM? | **Ollama (llama3.1:8b + qwen2.5-coder:14b)** | Local fallback for resilience and air-gap |
| Languages supported? | **6 Tier-1, 4 Tier-2, 100+ Tier-3** | Honest tiered coverage via adapter pattern (dropped overclaimed Tier-2 to languages we can maintain) |
| Frontend? | **React + Tailwind** | Production-grade UX, free diff viewer libraries, streaming for Patcher + Explainer |
| Observability? | **Langfuse (self-hosted)** | Production-grade tracing without SaaS lock-in |
| Bug memory? | **ChromaDB (persistent, always on)** | Compounding long-term quality; pre-seeded with golden dataset for demos |
| Security review? | **4-layer with diff regression** | Unique differentiator (AST patterns consolidated into Layer 2 Semgrep rules) |
| Best-of-N? | **Internal last-resort fallback only** | Not user-facing; runs only after 2 retries fail |
| Multi-modal input (OCR)? | **Deferred to v2** | Text input covers 95% of real flows |
| Target latency? | **P50 ~6s perceived (~9s wall-clock), P95 ~13s** | Streaming + caching + parallelism + short-circuit |
| Build order? | **Incremental, agent-by-agent, language-by-language** | Each step delivers a demoable system |

---

**End of document.**

*This is the architecture. Build it incrementally. Test it continuously. Ship it when each piece is verifiably correct.*

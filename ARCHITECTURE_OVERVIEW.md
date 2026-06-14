# Praman Setu — Solution Architecture (High-Level)

> **Praman Setu** ("bridge of proof") is an autonomous Python debugging-and-repair
> assistant. You paste a buggy file (optionally with a traceback); it returns
> **repaired code whose correctness is mechanically proven**, plus a tiered,
> de-duplicated list of anything it could not prove and left for a human.
>
> The name captures the core thesis: **don't *claim* a fix is correct — *prove* it.**
> Every accepted change has passed an execution-backed validator, and suspected
> logic bugs are escalated from "the model thinks so" to "a failing test proves so."

---

## 1. What problem it solves

Ordinary "ask an LLM to fix my code" has three failure modes this system is built to defeat:

| Failure mode | How Praman Setu defeats it |
|---|---|
| **The model says it fixed it, but it didn't** | A deterministic **5-gate Validator** runs the patched file in a sandbox. No green gates → the patch is rejected, never returned. |
| **It fixes the first crash and stops** | A whole-file **Bug Ledger** maps *all* defects up front (syntax, runtime, anti-patterns), so one pass addresses the whole file, not just line 1. |
| **It silently changes behavior / guesses business rules** | A **Critic** + **Property Tester** audit the *working* code; objective bugs are auto-fixed and re-validated, while intent-dependent choices are flagged, not guessed (configurable). |

---

## 2. System topology

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Frontend  (React + Vite + Monaco)            frontend/src/App.tsx            │
│  • Code editor, optional traceback box, 8-stage pipeline strip               │
│  • Consumes Server-Sent Events; renders Final Code (diff), Issues, Attempts, │
│    Explanation, Human Review tabs                                            │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │  POST /api/repair-v2/stream  (SSE)
                                ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  Backend  (FastAPI + uvicorn)                 backend/main.py                 │
│                                                                              │
│   Smart Input Handler ─► Bug Ledger ─► Repair Agent ─► Patch Applier ─►       │
│   Validator  ──(clean)──►  Explainer ‖ Critic ‖ Property Tester              │
│                                  └──► Review-driven re-repair (proof_repair)  │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │  docker exec  (per code run)
                                ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  Hardened Sandbox Pool   praman-setu-sandbox-python:latest                    │
│  • Network-off, read-only rootfs, non-root, mem/PID/CPU capped, tmpfs only   │
│  • Warm pool of idle containers reused via `docker exec` (~50–100ms/call)    │
└────────────────────────────────────────────────────────────────────────────┘
```

**Two LLM providers, one interface:** Groq (primary, fast hosted inference) with a
local **Ollama** fallback on timeout/error — see [backend/llm/client.py](backend/llm/client.py).

---

## 3. The primary workflow — `repair_v2` (pasted-file repair)

This is the product path. The 8 UI stages map directly to backend events.

### Stage-by-stage

| # | Stage | What happens | Working file |
|---|-------|--------------|--------------|
| 1 | **Smart Input Handler** | Detect language; **run the file once** in the sandbox under a `sys.settrace` harness to capture the real crash + local-variable snapshots (or confirm it runs clean). This is the system's *single* user-code execution. | [input_handler/service.py](backend/input_handler/service.py), [tools/tracer.py](backend/tools/tracer.py) |
| 2 | **Bug Ledger** | Build a whole-file defect map with **no LLM, no execution**: syntax/runtime errors + an AST **semantic linter** (mutable defaults, swallowed exceptions, ignored returns, infinite loops, non-daemon background threads). | [tools/bug_ledger.py](backend/tools/bug_ledger.py), [tools/semantic_lint.py](backend/tools/semantic_lint.py) |
| 3 | **Repair Agent** | One Groq call gets the ledger + numbered source and returns **whole corrected "units"** (a function/class by name, `<module>`, or `<file>`) — not text fragments. | [agents/multi_issue_fixer.py](backend/agents/multi_issue_fixer.py) |
| 4 | **Patch Applier** | Deterministically splice each unit back via the **AST** (locate by node, compile-check after every splice). A unit that won't compile is skipped, not allowed to corrupt the file. | [tools/patch_applier.py](backend/tools/patch_applier.py) |
| 5 | **Validator** | Re-run the candidate in the sandbox: must compile, run clean, and pass the security scan. On failure, the errors become feedback for another pass (up to `max_passes`). | [orchestrator/repair_v2.py](backend/orchestrator/repair_v2.py), [tools/diff_regression.py](backend/tools/diff_regression.py) |
| 6 | **Explainer** | Plain-language narrative of what was broken/fixed. Verification claim is **derived from the proven status** (never hallucinated). | [agents/explainer.py](backend/agents/explainer.py) |
| 7 | **Critic** | Semantic audit of the *working* code along general correctness axes (init value, boundary, return contract, edge case, shared state, invariant). Flags suspected latent logic bugs. | [agents/critic.py](backend/agents/critic.py) |
| 8 | **Property Tester** | Generates **Hypothesis** property tests asserting *intent-independent* invariants, runs them in the sandbox, and turns "suspected" bugs into **proven** ones with a counterexample. | [agents/property_tester.py](backend/agents/property_tester.py), [tools/test_module_constructor.py](backend/tools/test_module_constructor.py) |

### Review-driven re-repair (the closing loop)

After stages 6–8, the **objective** findings (proven counterexamples, the Critic's
non-intent concerns, deterministic linter hits) are fed *back* to the Repair Agent
to **fix, not just flag**. Each candidate must re-compile, re-run clean, and stay
secure (the Validator acts as a regression gate) before it's accepted — so review
**never makes the code worse**. Intent-ambiguous items get a best-guess fix and
stay flagged for confirmation.

➡ [orchestrator/proof_repair.py](backend/orchestrator/proof_repair.py) — `refine_with_review`

### Findings classification (signal, not noise)

All review signals are merged into one tiered list so the UI shows *confidence*:

- **confirmed** — proven by a failing property test (counterexample)
- **likely** — deterministic linter pattern / high-confidence Critic concern
- **potential** — intent-dependent or lower-confidence

Already-fixed bugs are dropped (ledger re-built on the final code), duplicates
across sources are merged, and low-value speculative questions are suppressed.

➡ [agents/findings.py](backend/agents/findings.py) — `classify_findings`

---

## 4. Architectural innovations

These are the design decisions that make the system more than a prompt wrapper.

### ① Proof over assertion — the deterministic 5-gate Validator
Correctness is **mechanically gated**, not model-asserted. The validator splices
the patch into the full module and runs, in the sandbox:

1. **Gate 1 — Syntax** (tree-sitter, fail-fast)
2. **Gate 2 — Types** (mypy; informational delta vs. original)
3. **Gate 3 — Security** (bandit; HIGH severity is an absolute floor)
4. **Gate 4 — Tests** (the generated test must pass)
5. **Gate 5 — Diff regression** (rejects *newly introduced* HIGH/MEDIUM findings)

Plus **anti-cheat guards** that reject non-fixes: an empty stub, a bare
`except: pass` swallow, or an unconditional re-raise of the original error.
➡ [tools/validator.py](backend/tools/validator.py)

### ② Whole-file Bug Ledger — no "first-crash tunnel vision"
A cheap, local, LLM-free map of *every* defect (errors + AST anti-patterns) is
built **before** the first model call, so the Repair Agent sees the whole file.
➡ [tools/bug_ledger.py](backend/tools/bug_ledger.py) + [tools/semantic_lint.py](backend/tools/semantic_lint.py)

### ③ AST unit-splicing — robust edit application
The model returns **complete code units**; the system locates them by AST node and
splices with a **compile-check after each edit**. This eliminates the two classic
LLM-patch failure modes: brittle string-match `old` blocks and indentation
corruption. `<file>` mode is the escape hatch when the source won't even parse.
➡ [tools/patch_applier.py](backend/tools/patch_applier.py)

### ④ Prove-the-logic-bug — Critic + Property Tester
Logic bugs in code that *runs fine* (e.g. `best = 0` returns 0 for an all-negative
list) never crash, so gates can't catch them. The **Critic reasons**; the
**Property Tester proves** via Hypothesis-generated counterexamples — but only on
**intent-independent invariants** (a `max` returns a member of its input; a length
is non-negative), never guessed business values. Proven bugs become objective
inputs to the re-repair loop.
➡ [agents/critic.py](backend/agents/critic.py), [agents/property_tester.py](backend/agents/property_tester.py)

### ⑤ Review that repairs, gated by the validator
Most tools flag and stop. Here the reviewers' objective findings are fed back and
**fixed**, with the full validator re-run as a regression gate so a "fix" can never
regress compile/run/security. ➡ [orchestrator/proof_repair.py](backend/orchestrator/proof_repair.py)

### ⑥ Execution tracer — observed values, not speculation
The single user-code run happens under a `sys.settrace` harness that records
local variables at each line and the crash state, giving downstream agents
*observed* evidence. User code is compiled under a virtual filename so line
numbers and `SyntaxError` linenos are exact.
➡ [tools/tracer.py](backend/tools/tracer.py)

### ⑦ Warm hardened sandbox pool — security *and* speed
Every code run is fully isolated: `--network=none`, read-only rootfs, all
capabilities dropped, non-root, memory/PID/CPU capped, writable area is tmpfs only
(wiped between calls). Containers are **pre-warmed and reused via `docker exec`**,
cutting per-call overhead from ~700–2000 ms (run/rm) to ~50–100 ms, with automatic
cold-path fallback and overflow handling.
➡ [tools/sandbox/pool.py](backend/tools/sandbox/pool.py), [tools/sandbox/executor.py](backend/tools/sandbox/executor.py)

### ⑧ Deterministic non-termination neutralization
A file that starts a non-daemon background worker at import time hangs headless
validation forever. The system detects this statically and **rewrites the thread
to `daemon=True`** (AST-precise, comments preserved) so it can be validated —
while *not* flagging already-daemon threads (they terminate fine).
➡ [tools/neutralize.py](backend/tools/neutralize.py), [tools/semantic_lint.py](backend/tools/semantic_lint.py)

### ⑨ Tiered, de-duplicated findings — confidence, not a pile
Three sources (linter / Critic / Property Tester) are merged into one list ranked
by *proof strength*, with already-fixed and duplicate findings removed, so the
"Human Review" surface stays high-signal. ➡ [agents/findings.py](backend/agents/findings.py)

### ⑩ Per-role model routing + provider fallback
Each agent role is mapped to a right-sized model (reasoning vs. code-gen) in a
single registry, and the LLM client transparently fails over from Groq to a local
Ollama model (with its own longer CPU timeout) on any error.
➡ [llm/models.py](backend/llm/models.py), [llm/client.py](backend/llm/client.py)

### ⑪ Streaming, resumable orchestration
Repair progress streams to the UI as Server-Sent Events (one event per
stage/snapshot). The legacy graph path persists every node transition to a SQLite
checkpoint store so a run can resume after an LLM timeout.
➡ [main.py](backend/main.py) (SSE), [orchestrator/graph.py](backend/orchestrator/graph.py) (checkpointing)

---

## 5. Feature → file map (quick reference)

### API surface — [backend/main.py](backend/main.py)
| Endpoint | Purpose |
|---|---|
| `GET /health` | Provider, sandbox-pool, checkpointing status |
| `POST /api/input/handle` | Run the Smart Input Handler only |
| `POST /api/analyze` | Full single-bug LangGraph pipeline (with `?debug=true` trace) |
| `POST /api/repair-v2` | **Primary** whole-file repair (JSON result) |
| `POST /api/repair-v2/stream` | **Primary** repair as SSE (what the UI uses) |
| `POST /api/fix` | Repair entry with `strategy=repair_v2 \| iterative`, `stream=true` |

### Agents — [backend/agents/](backend/agents/)
| File | Role |
|---|---|
| [multi_issue_fixer.py](backend/agents/multi_issue_fixer.py) | Whole-file Repair Agent (unit rewrites) — `repair_v2` path |
| [critic.py](backend/agents/critic.py) | Semantic logic audit of the accepted fix |
| [property_tester.py](backend/agents/property_tester.py) | Hypothesis property-test generation + proof |
| [explainer.py](backend/agents/explainer.py) | Human-readable repair narrative |
| [findings.py](backend/agents/findings.py) | Tiered, de-duplicated findings classifier |
| [diagnoser.py](backend/agents/diagnoser.py) | Legacy: hypothesis generation + test (graph path) |
| [patcher.py](backend/agents/patcher.py) | Legacy: single-function diff patcher (graph path) |
| [reflector.py](backend/agents/reflector.py) | Legacy: strategic retry/escalation decision (graph path) |
| [prompts/](backend/agents/prompts/) | Externalized diagnoser/patcher prompts |

### Orchestration — [backend/orchestrator/](backend/orchestrator/)
| File | Role |
|---|---|
| [repair_v2.py](backend/orchestrator/repair_v2.py) | **Primary** repair loop (ledger → fix → splice → validate) |
| [proof_repair.py](backend/orchestrator/proof_repair.py) | Review-driven re-repair, validator-gated |
| [graph.py](backend/orchestrator/graph.py) | Legacy LangGraph: Context→Diagnoser→Patcher→Validator→Reflector |
| [iterative.py](backend/orchestrator/iterative.py) | Legacy multi-bug iterative loop over the graph |
| [state.py](backend/orchestrator/state.py) | Shared Pydantic state + data models |

### Deterministic tools — [backend/tools/](backend/tools/)
| File | Role |
|---|---|
| [bug_ledger.py](backend/tools/bug_ledger.py) | Whole-file defect map (no LLM) |
| [semantic_lint.py](backend/tools/semantic_lint.py) | AST anti-pattern linter |
| [neutralize.py](backend/tools/neutralize.py) | Non-termination → `daemon=True` rewrite |
| [patch_applier.py](backend/tools/patch_applier.py) | AST unit-splicing edit application |
| [validator.py](backend/tools/validator.py) | 5-gate validator + anti-cheat guards (graph path) |
| [diff_regression.py](backend/tools/diff_regression.py) | Bandit scan + before/after safety delta |
| [tracer.py](backend/tools/tracer.py) | `settrace` execution evidence capture |
| [context_builder.py](backend/tools/context_builder.py) | Tree-sitter context packet (graph path) |
| [test_module_constructor.py](backend/tools/test_module_constructor.py) | AST-safe import-clean test module builder |
| [sandbox/pool.py](backend/tools/sandbox/pool.py) | Warm container pool |
| [sandbox/executor.py](backend/tools/sandbox/executor.py) | Hardened container exec primitives |

### Infrastructure
| File | Role |
|---|---|
| [llm/client.py](backend/llm/client.py) | Groq client w/ structured output + Ollama fallback |
| [llm/models.py](backend/llm/models.py) | Per-role model registry |
| [config.py](backend/config.py) | Settings (keys, provider, sandbox timeout) |
| [observability/metrics.py](backend/observability/metrics.py) | LLM-call + run-trace metrics |
| [frontend/src/App.tsx](frontend/src/App.tsx) | Single-page UI (editor, pipeline strip, SSE, tabs) |
| [docker-compose.yml](docker-compose.yml) | backend (8000) + frontend (5173) + sandbox image |

---

## 6. Two pipelines, one product

| | **`repair_v2`** (primary) | **LangGraph graph** (legacy/diagnostic) |
|---|---|---|
| Input | Whole pasted file | Single bug + built context |
| Scope | All defects at once | One bug, with retry escalation |
| Strategy | Bug ledger → unit rewrite → full-file validate | Context→Diagnoser→Patcher→**5-gate Validator**→Reflector |
| Fix unit | Functions/`<module>`/`<file>` | Single function diff |
| Retries | `max_passes` with validation feedback | Reflector escalates H1→H2→H3, persisted via checkpointer |
| Entry | `/api/repair-v2[/stream]`, `/api/fix?strategy=repair_v2` | `/api/analyze`, `/api/fix?strategy=iterative` |

`repair_v2` is the default product experience; the graph path remains for
single-bug analysis, the richer 5-gate validator, and fault-tolerant resumable runs.

---

## 7. Design principles (the throughline)

1. **Prove, don't claim.** Nothing is returned as "fixed" unless execution backs it.
2. **Deterministic where possible, LLM only where necessary.** Ledger, splicing,
   validation, neutralization, and classification are all deterministic; the model
   is used for the creative steps (repair, review, narrative) and always re-checked.
3. **Right tool for the bug class.** Crashes → gates; latent logic bugs → property
   proofs; anti-patterns → static linter.
4. **Never guess intent silently.** Objective bugs are fixed and proven;
   intent-dependent choices are surfaced (or best-guessed *and* flagged).
5. **Fail safe.** Every agent has a deterministic fallback and never blocks the
   response; the sandbox is locked down by default.

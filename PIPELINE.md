# Praman Setu — Current Pipeline (detailed)

This document describes the **repair_v2** pipeline as it exists today: the primary
path for repairing a pasted Python file. It covers every stage, the agents and
tools involved, the data that flows between them, the API surface, the streaming
events, the frontend, and the known limits.

---

## 1. High-level overview

Praman Setu takes a pasted Python file and returns a **repaired file plus proof
and explanation**. The design principle is *prove, don't claim*: every fix is
validated by actually running the code in a hardened sandbox, and crash fixes are
additionally proven by a reproduction test that must fail on the broken code and
pass on the fixed code.

```
                                   repair_v2 pass loop (≤ max_passes)
 ┌───────────────────────────────────────────────────────────────────────────┐
 │  1 Smart Input Handler  →  2 Bug Ledger  →  3 Diagnoser*  →  4 Repair Agent │
 │        (reproduce)            (static map)     (root cause +     (whole-unit │
 │                                                 repro test)*      rewrites)  │
 │                                                                             │
 │  →  5 Patch Applier  →  6 Validator (concurrent)  →  (retry with feedback)  │
 │       (AST splice)        reproduce ‖ security ‖ reproduction-proof          │
 └───────────────────────────────────────────────────────────────────────────┘
                                     │ on success / exhausted
                                     ▼
                    7 Explainer   +   8 Critic   (run concurrently)
              (plain-language fixes)   (root-cause / intent / latent-logic audit)

 * The Diagnoser runs only on a "crash pass" — compilable code with a runtime error.
```

Entry point: [`repair_v2()`](backend/orchestrator/repair_v2.py). The loop runs up
to `max_passes` (default 3, clamped 1–5). Each pass either returns a terminal
result or produces feedback that steers the next pass.

---

## 2. Stage-by-stage

### 1. Smart Input Handler — reproduce
File: `backend/input_handler/`, called via `handler.handle(RawInput(...))`.

- Detects the language (Python-only today) and **runs the code once in the
  sandbox** through an execution tracer.
- Produces a `ProcessedInput`: `status` (`execution_clean` / `execution_failed` /
  `execution_timeout`), `error_type`, `error_line`, `error_message`, plus an
  execution trace. `input()` is handled so headless runs don't hang.
- This is the ground-truth "does it crash, and how" signal for the pass.

### 2. Bug Ledger — deterministic static map
File: [`build_bug_ledger()`](backend/tools/bug_ledger.py).

- Pure `ast` + `builtins` analysis (no LLM). Produces a `BugLedger`:
  `code_compiles`, `issues[]`, `imports`, `functions`, `classes`,
  `top_level_executable_lines`, `top_level_input_lines`, and the
  `runtime_error_*` fields carried from the Input Handler.
- `prompt_summary()` renders a compact whole-file map that the Repair Agent reads.
- **Early exits computed here:**
  - If `status == execution_clean` → run the security scan; if clean, **return
    `clean`**; if insecure, set feedback and keep going.
  - If `not code_compiles` (SyntaxError) → seed feedback telling the agent to
    return a single `<file>` rewrite (you can't AST-splice an unparseable file).

### 3. Diagnoser — root cause + reproduction test  *(crash passes only)*
File: [`diagnoser.py`](backend/agents/diagnoser.py); wired in
[`repair_v2.py`](backend/orchestrator/repair_v2.py) via `_diagnose()`.

- **Gate:** runs only when `code_compiles and runtime_error_type is not None`
  (a real runtime crash in parseable code). Skipped for syntax-only, clean, or
  security-only passes.
- Builds a `ContextPackage` (`context_builder.build`) and calls the Diagnoser LLM,
  producing a `DiagnoserOutput`: `root_cause`, three `hypotheses`
  (`theory` / `confidence` / `fix_direction`), and a **reproduction test**.
- Effects:
  - The `root_cause` + top `fix_direction` are prepended to the Repair Agent's
    feedback (`_with_diagnosis`) so it patches with reasoning.
  - The reproduction test is handed to the Validator as a **proof gate** (step 6).
- **Best-effort:** wrapped so any failure returns `None` and the pipeline
  proceeds without it — diagnosis never blocks a repair.
- Currently only `H1`'s direction is used; `H2`/`H3` are produced but not yet
  driving retries (Reflector escalation is a deliberate not-yet-built option).

### 4. Repair Agent (MultiIssueFixer) — whole-unit rewrites
File: [`multi_issue_fixer.py`](backend/agents/multi_issue_fixer.py).

- **One LLM call** that reads the bug-ledger map (+ any feedback/diagnosis) and
  returns a `MultiIssueFixResponse`: `summary`, `issues_found[]`, `confidence`,
  optional `generated_tests`, and a list of **units** to rewrite.
- A *unit* (`UnitRewrite`) is a complete corrected code block identified by:
  - a top-level **function/class name**, or
  - `"<module>"` — the trailing top-level executable block, or
  - `"<file>"` — the entire file (required when the code doesn't parse).
- This whole-unit model replaced fragile `old`/`new` string edits: the agent
  returns complete, coherent units, not text fragments that must match verbatim.
- Wrapped fail-safe: if Groq **and** the Ollama fallback are unreachable, the
  pipeline returns `unresolved` instead of crashing.

### 5. Patch Applier — deterministic AST splice
File: [`apply_unit_rewrites()`](backend/tools/patch_applier.py).

- Locates each unit by name in the AST and splices its `new_source` in.
- **Compile-checked after every unit**: a rewrite that wouldn't parse is dropped
  (recorded as a failure) — the good units still land. This eliminates the two
  old failure modes: "old block not found" and indentation corruption.
- `<file>` units replace the whole file (the only option for unparseable input).
- If **no** unit applied but units were proposed, the loop retries with a message
  telling the agent its targets/sources were rejected (instead of giving up).

### 6. Validator — concurrent proof
File: `_validate_candidate()` in [`repair_v2.py`](backend/orchestrator/repair_v2.py).

After splicing, the candidate is validated. The independent checks run
**concurrently** (the warm pool holds 4 idle containers), so wall time is the
slowest single check, not the sum:

1. **Compile** — `ast.parse` (fast, fail-fast).
2. **Reproduce** — `handler.handle` runs the patched file; must be
   `execution_clean` (not failed/timed-out). This clean run is reused to build the
   final ledger (no extra reproduce).
3. **Security** — `scan_code` runs **bandit** in the sandbox; any HIGH/MEDIUM
   finding fails the gate.
4. **Reproduction proof** (crash passes) — the diagnosed test is run on the
   **patched** code. Since the Input Handler already proved the original crashes,
   one run suffices: PASS ⇒ `proven`, FAIL ⇒ `not_resolved` (rejects the pass).
   The agent's own `generated_tests` are skipped when a reproduction test exists
   (it's the stronger, targeted proof — saves a pytest run).

If any check fails, its message becomes the next pass's feedback. If all pass,
the pass returns `clean`.

### 7. Explainer — user-facing narrative
File: [`explainer.py`](backend/agents/explainer.py). Runs once after the loop.

- One LLM call over the before/after code → `RepairExplanation`: `headline`,
  per-fix `fixes[]` (issue / fix / category), and `flagged[]`.
- The `verification` line is **derived deterministically from the validated
  status**, never from the LLM (so the proof claim can't be hallucinated).
- Deterministic fallback if the LLM is down — never blocks the response.

### 8. Critic — semantic review + latent-logic audit
File: [`critic.py`](backend/agents/critic.py). Runs concurrently with the Explainer.

- Explicitly does **not** re-check compile/run/security (the Validator already
  proved those). Two jobs:
  1. **Review the fixes** — per-fix `addresses_root_cause` / `preserves_intent` /
     `confidence`.
  2. **Audit the whole final program for latent logic bugs** — wrong formulas,
     bad initial values, ignored return values, off-by-one/boundary errors — even
     in code that wasn't changed.
- `needs_human_review[]` is the authoritative "a human should look at this" list;
  `overall` ∈ {solid, acceptable, risky, unassessed}.
- Deterministic `unassessed` fallback; never blocks.

---

## 3. The pass loop & terminal statuses

Each pass: reproduce → ledger → (diagnose) → fix → apply → validate. Outcomes:

| status | meaning |
|---|---|
| `clean` | patched file compiles, runs clean, passes security (and reproduction proof) |
| `unresolved` | passes exhausted with a remaining error, or the LLM was unavailable |
| `no_progress` | the agent proposed edits but none could be applied, and no retry was possible |
| `insecure` | runs clean but a security finding remains, so it wasn't accepted as clean |

Result shape (`RepairV2Result`): `status`, `passes`, `original_code`,
`final_code`, `ledger`, `attempts[]` (per-pass summary/applied/failures/validation
errors/confidence), `remaining_error`.

---

## 4. Agents & model routing

Single registry: [`backend/llm/models.py`](backend/llm/models.py) — one place to
right-size models per role (primary on Groq, fallback on local Ollama):

| role | primary (Groq) | fallback (Ollama) |
|---|---|---|
| diagnoser | `meta-llama/llama-4-scout-17b-16e-instruct` | `llama3.1:8b` |
| patcher | `qwen/qwen3-32b` | `qwen2.5-coder:7b` |
| reflector | `meta-llama/llama-4-scout-17b-16e-instruct` | `llama3.1:8b` |
| explainer | `meta-llama/llama-4-scout-17b-16e-instruct` | `llama3.1:8b` |
| critic | `meta-llama/llama-4-scout-17b-16e-instruct` | `llama3.1:8b` |

LLM client: [`backend/llm/client.py`](backend/llm/client.py) — Groq-first; on an
HTTP/timeout error it falls back to the same role's local Ollama model. JSON is
parsed straight into Pydantic models (structured outputs).

---

## 5. The sandbox

File: [`backend/tools/sandbox/`](backend/tools/sandbox/). All untrusted execution
(reproduce, bandit, pytest) happens in a hardened container:
`--network=none`, `--read-only` rootfs, `--cap-drop=ALL`, non-root user, tmpfs
workspace. A **pre-warmed pool** (4 idle containers) keeps per-call overhead low
(~50–100 ms acquire vs ~1–2 s cold `docker run`); overflow falls back to the cold
path. Warmed at FastAPI startup, drained at shutdown.

---

## 6. API surface

File: [`backend/main.py`](backend/main.py).

- `POST /api/repair-v2?explain=&critique=&max_passes=` → `{result, explanation,
  critique}` (Explainer + Critic run concurrently).
- `POST /api/repair-v2/stream?...` → **Server-Sent Events** for live UI progress.
- `POST /api/fix?strategy=repair_v2|iterative&stream=` → repair_v2 (default) or the
  legacy single-bug iterative graph.
- `POST /api/analyze` → legacy single-bug pipeline (Diagnoser→Patcher→Validator→
  Reflector graph) for diagnostics.
- `GET /health` → provider, sandbox pool status, checkpointing.

### SSE events (in order)
`phase` (a stage went running) · `input` · `ledger` · `diagnosis` ·
`repair` · `patch` · `reproduction` · `validation` · `attempt` ·
`explanation` · `critique` · `done` · `error`.

---

## 7. Frontend

File: [`frontend/src/App.tsx`](frontend/src/App.tsx) (+ `App.css`), Vite + React.

- Top-left **Repair** button; an animated **pipeline strip** lights up each of the
  8 stages live from the SSE events.
- **Monaco** editor for input; **Final Code** tab is a Monaco inline diff
  (GitHub-style red/green) — selecting/copying yields only the kept + added lines
  (removed lines live in the original model), and a "Copy patched code" button
  copies the clean final.
- Tabs: Final Code · Issues · Attempts · Explanation · Human Review (the Critic's
  per-fix verdicts + latent-logic audit + needs-human-review list).
- Theme matches VS Code "Dark Modern".

---

## 8. Timing (typical single-crash repair, warm)

```
input handler    ~0.4s   sandbox reproduce
Diagnoser (LLM)  ~2.0s   crash passes only
repair    (LLM)  ~0.7s
validation       ~2.0s   reproduce ‖ bandit ‖ reproduction-proof (concurrent)
explainer+critic ~1.2s   concurrent, after the patch
```

Per-op sandbox costs (warm): reproduce ~0.37s, bandit ~0.73s, pytest ~1.0s. The
two dominant costs are the **LLM round-trips** and the **hardened-sandbox Docker
overhead** (the price of safe execution).

---

## 9. What it does well vs. its limits

**Strong:**
- Syntax / crash / security bugs — fixed reliably, each fix sandbox-proven; crash
  fixes additionally proven by a fail-before/pass-after reproduction test.
- No silent corruption (compile-gated AST splice) and no false "clean".

**Limited (by design / honesty):**
- **Logic bugs without a crash** are *detected and flagged* (Critic's latent-logic
  audit), not auto-fixed — fixing them needs the user's intent.
- The Diagnoser only fires on runtime crashes in compilable code.
- A reproduction proof is only as strong as the LLM-generated test.
- `H2`/`H3` hypotheses are generated but not yet driving retries (Reflector
  escalation is a future option).

"""Run the full repair_v2 workflow and dump every agent's output to a Markdown file.

Usage:
    uv run python -m backend.tools.dump_agent_outputs            # uses the built-in 8-bug sample
    uv run python -m backend.tools.dump_agent_outputs path.py    # uses your own file
    uv run python -m backend.tools.dump_agent_outputs path.py out.md

Captures, in order: Input Handler -> Bug Ledger -> Patcher (per pass) ->
Patch Applier -> Validator -> final result -> Explainer -> Critic.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from backend.agents.critic import CriticAgent
from backend.agents.explainer import ExplainerAgent
from backend.agents.multi_issue_fixer import MultiIssueFixerAgent, MultiIssueFixResponse
from backend.input_handler.models import RawInput
from backend.input_handler.service import smart_input_handler
from backend.llm.client import llm_client
from backend.tools.bug_ledger import BugLedger

_SAMPLE = '''def summarize(items)
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

def label(n):
    return "id-" + n

if __name__ == "__main__":
    data = [{"price": 100, "tax": 18}, {"price": 50, "tax": 9}]
    print(summarize(data))
    print(average([10, 20, 30]))
    print(label(42))
    user_input = input("expr: ")
    eval(user_input)
'''


class _RecordingHandler:
    """Wraps the real input handler and records every ProcessedInput it returns."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls: list = []

    async def handle(self, request: RawInput):
        result = await self.inner.handle(request)
        self.calls.append(result)
        return result


class _RecordingFixer:
    """Wraps the Patcher agent and records each (ledger, response) per pass."""

    def __init__(self, inner: MultiIssueFixerAgent) -> None:
        self.inner = inner
        self.records: list[tuple[BugLedger, MultiIssueFixResponse]] = []

    async def fix(self, code: str, ledger: BugLedger, *, validation_feedback: str = ""):
        response = await self.inner.fix(code, ledger, validation_feedback=validation_feedback)
        self.records.append((ledger, response))
        return response


def _fence(code: str, lang: str = "python") -> str:
    return f"```{lang}\n{code.rstrip()}\n```"


def _processed_block(p) -> str:
    return (
        f"- **status:** `{p.status}`\n"
        f"- **error_type:** `{p.error_type}`\n"
        f"- **error_line:** `{p.error_line}`\n"
        f"- **error_message:** {p.error_message or '_(none)_'}"
    )


def _ledger_block(ledger: BugLedger) -> str:
    return _fence(ledger.prompt_summary(), "text")


def _patcher_block(response: MultiIssueFixResponse) -> str:
    lines = [
        f"- **summary:** {response.summary}",
        f"- **confidence:** `{response.confidence}`",
        f"- **issues_found:** {response.issues_found or '_(none)_'}",
        f"- **units returned:** {len(response.units)}",
    ]
    for i, u in enumerate(response.units, 1):
        lines.append(f"\n  **Unit {i} — target `{u.target}`** — {u.reason or '_(no reason given)_'}")
        lines.append(_fence(u.new_source))
    if response.generated_tests.strip():
        lines.append("\n  **generated_tests:**")
        lines.append(_fence(response.generated_tests))
    return "\n".join(lines)


async def main() -> None:
    src_arg = sys.argv[1] if len(sys.argv) > 1 else None
    out_arg = sys.argv[2] if len(sys.argv) > 2 else "AGENT_OUTPUTS.md"
    code = Path(src_arg).read_text(encoding="utf-8") if src_arg else _SAMPLE
    filename = Path(src_arg).name if src_arg else "app.py"

    from backend.orchestrator.repair_v2 import repair_v2  # local import: avoids cycle at module load

    handler = _RecordingHandler(smart_input_handler)
    fixer = _RecordingFixer(MultiIssueFixerAgent(llm_client))

    result = await repair_v2(code, filename, max_passes=4, handler=handler, fixer=fixer)
    explanation, critique = await asyncio.gather(
        ExplainerAgent(llm_client).explain(result),
        CriticAgent(llm_client).review(result),
    )
    await llm_client.aclose()

    md: list[str] = []
    md.append("# Praman Setu — full agent-by-agent workflow output\n")
    md.append(f"**File:** `{filename}`  ·  **Final status:** `{result.status}`  ·  **Passes:** {result.passes}\n")

    md.append("## 0. Original (input) code\n")
    md.append(_fence(code))

    md.append("\n## 1. Input Handler (initial reproduction)\n")
    md.append(_processed_block(handler.calls[0]) if handler.calls else "_no calls recorded_")

    # Per-pass: Bug Ledger -> Patcher -> Applier -> Validator
    for i, ((ledger, patch_resp), attempt) in enumerate(zip(fixer.records, result.attempts), start=1):
        md.append(f"\n## Pass {i}\n")
        md.append("### 2. Bug Ledger (deterministic static analysis)\n")
        md.append(_ledger_block(ledger))
        md.append("\n### 3. Patcher Agent (MultiIssueFixer)\n")
        md.append(_patcher_block(patch_resp))
        md.append("\n### 4. Patch Applier (AST unit splice)\n")
        md.append(f"- **units applied:** {attempt.applied_edits}")
        md.append(f"- **apply failures:** {attempt.edit_failures or '_(none)_'}")
        md.append("\n### 5. Validator (compile · sandbox run · security · tests)\n")
        md.append(f"- **validation errors:** {attempt.validation_errors or '_(none — passed)_'}")

    md.append("\n## 6. Final repaired code\n")
    md.append(_fence(result.final_code))
    if result.remaining_error:
        md.append(f"\n**remaining_error:** {result.remaining_error}")

    md.append("\n## 7. Explainer Agent (user-facing narrative)\n")
    md.append(f"- **headline:** {explanation.headline}")
    md.append(f"- **verification:** {explanation.verification}")
    md.append("\n**Fixes:**")
    for f in explanation.fixes:
        md.append(f"- _[{f.category}]_ {f.issue} → {f.fix}")
    md.append("\n**Flagged (narrative):**")
    md.extend(f"- {x}" for x in (explanation.flagged or ["_(none)_"]))

    md.append("\n## 8. Critic Agent (semantic review)\n")
    md.append(f"- **overall:** `{critique.overall}`")
    md.append(f"- **summary:** {critique.summary}")
    md.append("\n**Per-fix assessments:**")
    for a in critique.assessments:
        md.append(
            f"- `{a.target}` — root_cause={a.addresses_root_cause}, "
            f"intent={a.preserves_intent}, confidence={a.confidence}"
            + (f"\n  - concern: {a.concern}" if a.concern else "")
        )
    md.append("\n**Latent logic audit (whole-program):**")
    if critique.logic_audit:
        md.extend(f"- _[{c.severity}]_ `{c.location}` — {c.issue}" for c in critique.logic_audit)
    else:
        md.append("- _(none)_")
    md.append("\n**Needs human review (authoritative):**")
    md.extend(f"- {x}" for x in (critique.needs_human_review or ["_(none)_"]))

    out_path = Path(out_arg)
    out_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Wrote {out_path.resolve()}  (status={result.status}, passes={result.passes})")


if __name__ == "__main__":
    asyncio.run(main())

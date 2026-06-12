"""Manual same-file realistic smoke test for the full Praman Setu graph.

This is intentionally small, not a golden dataset. It exercises medium-sized
single-file inputs through the live graph so we can see whether the current
pipeline handles more than toy snippets.

Requires:
- Docker running
- praman-setu-sandbox-python:latest built
- GROQ_API_KEY in .env, or a configured local Ollama fallback

Run with:
    uv run python -m backend.tools.realistic_smoke
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from backend.input_handler.models import RawInput
from backend.input_handler.service import smart_input_handler
from backend.orchestrator.graph import build_graph
from backend.orchestrator.state import PipelineState


@dataclass(frozen=True)
class SmokeCase:
    name: str
    filename: str
    code: str


CASES = [
    SmokeCase(
        name="class method calls helper with None email",
        filename="user_service.py",
        code="""DEFAULT_DOMAIN = "example.com"
DEFAULT_EMAIL = "unknown@example.com"


def normalize_email(value):
    return value.strip().lower()


def send_welcome_email(user):
    return f"Welcome {user.email}"


class User:
    def __init__(self, email):
        self.email = email


class UserService:
    cache_enabled = True

    def get_email(self, user):
        return normalize_email(user.email)

    def build_profile(self, user):
        return {
            "email": self.get_email(user),
            "domain": DEFAULT_DOMAIN,
        }


service = UserService()
print(service.build_profile(User(None)))
""",
    ),
    SmokeCase(
        name="same-file caller exposes missing dictionary key",
        filename="orders.py",
        code="""DEFAULT_DISCOUNT = 0


def get_discount(order):
    discount = order["discount"]
    return discount


def summarize_order(order):
    discount = get_discount(order)
    return f"Discount: {discount}"


print(summarize_order({"subtotal": 100}))
""",
    ),
    SmokeCase(
        name="class method uses missing instance default",
        filename="cart.py",
        code="""DEFAULT_TAX_RATE = 0.18


class Cart:
    def __init__(self, items, tax_rate=None):
        self.items = items
        self.tax_rate = tax_rate

    def subtotal(self):
        return sum(self.items)

    def total(self):
        return self.subtotal() + self.subtotal() * self.tax_rate


print(Cart([100]).total())
""",
    ),
]


async def run_case(case: SmokeCase) -> bool:
    start = time.monotonic()
    processed = await smart_input_handler.handle(RawInput(code=case.code, filename=case.filename))
    graph = build_graph()
    final = await graph.ainvoke(PipelineState(raw_input=processed, language=processed.language))
    elapsed = time.monotonic() - start

    report = final.get("validator_report")
    passed = bool(report and report.overall_passed)

    print(f"\n=== {case.name} ===")
    print(f"status={processed.status} error_type={processed.error_type} line={processed.error_line}")
    print(f"passed={passed} retry_count={final.get('retry_count', 0)} elapsed={elapsed:.2f}s")
    print(f"root_cause={getattr(final.get('diagnoser_output'), 'root_cause', '<none>')}")
    patch = final.get("patcher_output")
    if patch:
        print(f"approach={patch.approach}")
        print("diff:")
        print(patch.unified_diff)
    if report and not report.overall_passed:
        print("failures:")
        for failure in report.detailed_failures:
            print(f"- {failure}")

    return passed


async def main() -> None:
    results = [await run_case(case) for case in CASES]
    passed = sum(results)
    total = len(results)
    print(f"\nSUMMARY: {passed}/{total} passed")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())

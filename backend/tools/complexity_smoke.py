"""Three real cases of increasing complexity through the full live graph.

Run:  uv run python -m backend.tools.complexity_smoke
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter

from backend.input_handler.models import RawInput
from backend.input_handler.service import smart_input_handler
from backend.llm.client import llm_client
from backend.observability.metrics import build_run_trace
from backend.orchestrator.graph import build_graph
from backend.orchestrator.state import PipelineState


@dataclass(frozen=True)
class Case:
    name: str
    filename: str
    code: str


# 1 — one class, one method (ZeroDivisionError on empty cart)
CASE_1 = """class ShoppingCart:
    def __init__(self):
        self.items = []

    def add(self, price):
        self.items.append(price)

    def average_price(self):
        return sum(self.items) / len(self.items)


cart = ShoppingCart()
print(cart.average_price())
"""

# 2 — class + module-level helper (bug is in the callee parse_amount), uses a constant
CASE_2 = """TAX_RATE = 0.08


def parse_amount(raw):
    return float(raw)


class Invoice:
    def __init__(self, lines):
        self.lines = lines

    def subtotal(self):
        return sum(parse_amount(line) for line in self.lines)

    def total(self):
        return self.subtotal() * (1 + TAX_RATE)


invoice = Invoice(["10.00", "20.00", "$5.00"])
print(invoice.total())
"""

# 3 — two classes + two functions + constants + a call chain (KeyError deep in a callee)
CASE_3 = """DEFAULT_CURRENCY = "USD"
DISCOUNT_TABLE = {"gold": 0.2, "silver": 0.1}


def lookup_discount(tier):
    return DISCOUNT_TABLE[tier]


class Customer:
    def __init__(self, name, tier):
        self.name = name
        self.tier = tier


class Order:
    def __init__(self, customer, amount):
        self.customer = customer
        self.amount = amount

    def final_price(self):
        discount = lookup_discount(self.customer.tier)
        return self.amount * (1 - discount)


def checkout(order):
    price = order.final_price()
    return f"{price:.2f} {DEFAULT_CURRENCY}"


order = Order(Customer("Asha", "bronze"), 100.0)
print(checkout(order))
"""

CASES = [
    Case("1. class method ZeroDivisionError", "cart.py", CASE_1),
    Case("2. helper/callee ValueError + constant", "invoice.py", CASE_2),
    Case("3. multi-class call-chain KeyError", "orders.py", CASE_3),
]


async def run_case(graph, case: Case) -> None:
    print("\n" + "=" * 70)
    print(case.name)
    print("=" * 70)
    started = perf_counter()
    processed = await smart_input_handler.handle(RawInput(code=case.code, filename=case.filename))
    ih_ms = (perf_counter() - started) * 1000
    print(f"input    : {processed.error_type} @ line {processed.error_line}")

    final = await graph.ainvoke(PipelineState(raw_input=processed, language=processed.language))
    total_ms = (perf_counter() - started) * 1000

    diag = final.get("diagnoser_output")
    if diag is not None:
        print(f"diagnosis: scope={diag.affected_scope} | {diag.root_cause}")

    report = final.get("validator_report")
    patch = final.get("patcher_output")
    print(
        f"result   : passed={bool(report and report.overall_passed)} "
        f"retry={final.get('retry_count', 0)} human_review={final.get('human_review_flag')}"
    )
    if report is not None:
        print("gates    : " + "  ".join(f"{n}={g.passed}" for n, g in sorted(report.gate_results.items())))
    if patch is not None:
        print(f"patch target: {patch.patch_target}")
        print("--- patched_code ---")
        print(patch.patched_code)

    trace = build_run_trace(final, input_handler_ms=ih_ms, total_ms=total_ms)
    nt = trace["node_timings"]
    print(
        f"timing   : total={nt['total_ms']:.0f}ms diag={nt.get('diagnoser_ms', 0):.0f} "
        f"patch={nt.get('patcher_ms', 0):.0f} val={nt.get('validator_ms', 0):.0f} "
        f"tokens={trace['llm']['total_tokens']}"
    )


async def main() -> None:
    graph = build_graph()
    try:
        for case in CASES:
            await run_case(graph, case)
    finally:
        await llm_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())

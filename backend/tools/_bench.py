from __future__ import annotations
import asyncio
from time import perf_counter
from backend.llm.client import llm_client
from backend.orchestrator import repair_v2 as rv2
from backend.agents import multi_issue_fixer as mif

CODE = '''def summarize(items)
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

MODELS = ["qwen/qwen3-32b", "openai/gpt-oss-120b", "llama-3.3-70b-versatile"]

async def main() -> None:
    for m in MODELS:
        mif._MODEL = m
        t = perf_counter()
        try:
            r = await rv2.repair_v2(CODE, "app.py", max_passes=4)
            compiles = True
            try:
                compile(r.final_code, "f", "exec")
            except SyntaxError:
                compiles = False
            print(f"\n### {m}")
            print(f"    status={r.status} passes={r.passes} time={perf_counter()-t:.0f}s "
                  f"compiles={compiles} eval_gone={'eval(' not in r.final_code}")
            for a in r.attempts:
                print(f"    pass{a.pass_number}: applied={a.applied_edits} fail={len(a.edit_failures)} valerr={len(a.validation_errors)}")
            if r.remaining_error:
                print(f"    remaining: {r.remaining_error[:70]}")
        except Exception as e:
            print(f"\n### {m}\n    EXC {type(e).__name__}: {str(e)[:90]}")
    await llm_client.aclose()

asyncio.run(main())

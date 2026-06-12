import asyncio
from time import perf_counter

from backend.llm.client import llm_client
from backend.orchestrator.iterative import iterative_fix

CODE = '''import json

def load_configuration(raw_string):
    """Parse a configuration string into a dict."""
    return json.loads(raw_string)


config = load_configuration("{'debug': True, 'timeout': 30}")
print(config)
'''

async def main() -> None:
    from backend.tools.sandbox.pool import sandbox_pool
    from backend.input_handler.models import RawInput
    from backend.input_handler.service import smart_input_handler
    from backend.orchestrator.graph import build_graph
    from backend.orchestrator.state import PipelineState

    print("Warming sandbox pool...")
    await sandbox_pool.warm()

    print("Starting pipeline...\n")
    started = perf_counter()

    processed = await smart_input_handler.handle(RawInput(code=CODE, filename="test_code.py"))
    print(f"Input handler: status={processed.status}  error_type={processed.error_type}  line={processed.error_line}\n")

    graph = build_graph()
    state = PipelineState(raw_input=processed, language="python")
    final = await graph.ainvoke(state)
    elapsed = (perf_counter() - started) * 1000

    # --- Diagnoser ---
    diag = final.get("diagnoser_output")
    if diag:
        h1 = diag.hypotheses[0]
        print("=== DIAGNOSER ===")
        print(f"root_cause:      {diag.root_cause}")
        print(f"H1 theory:       {h1.theory}")
        print(f"H1 fix_direction:{h1.fix_direction}")
        print(f"generated_test:\n{diag.generated_test}\n")

    # --- Patcher ---
    patch = final.get("patcher_output")
    if patch:
        print("=== PATCHER ===")
        print(f"approach:      {patch.approach}")
        print(f"confidence:    {patch.confidence}")
        print(f"blocked_reason:{patch.blocked_reason}")
        print(f"patched_code:\n{patch.patched_code}\n")

    # --- Validator ---
    report = final.get("validator_report")
    if report:
        print("=== VALIDATOR ===")
        print(f"overall_passed: {report.overall_passed}")
        for gate, result in report.gate_results.items():
            status = "PASS" if result.passed else "FAIL"
            print(f"  {gate}: {status}", end="")
            if not result.passed and result.error:
                # Trim long pytest output to first 15 lines
                err = "\n".join(result.error.splitlines()[:15])
                print(f"\n    {err}")
            else:
                print()

    print(f"\nTotal: {elapsed:.0f}ms   retry_count={final.get('retry_count', 0)}")
    await llm_client.aclose()
    await sandbox_pool.drain()



if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from time import perf_counter

from backend.llm.client import llm_client
from backend.orchestrator.iterative import iterative_fix

CODE = """from typing import List, Dict, Optional
import json

class DataAggregator:
    def __init__(self, config: Dict):
        self.config = config
        self.results = []
    
    def parse_records(self, raw_json: str) -> List[Dict]:
        if not raw_json:
            return []
        data = json.loads(raw_json)
        return data.get("records", [])
    
    def compute_average(self, values: List[float]) -> float:
        total = sum(values)
        count = len(values)
        return total / count
    
    def process_record(self, record: Dict) -> Optional[str]:
        scores = record.get("scores", [])
        avg = self.compute_average(scores)
        max_score = max(scores)
        
        if avg > 80:
            return f"Excellent: avg={avg:.1f}, max={max_score}"
        elif avg > 50:
            return f"Good: avg={avg:.1f}, max={max_score}"
        return f"Poor: avg={avg:.1f}, max={max_score}"
    
    def run_analysis(self, raw_data: str) -> List[str]:
        records = self.parse_records(raw_data)
        return [self.process_record(r) for r in records]

aggregator = DataAggregator({"mode": "standard"})
test_data = '{"records": [{"scores": [90, 85, 88]}, {"scores": []}, {"scores": [45, 55]}]}'
output = aggregator.run_analysis(test_data)
for line in output:
    print(line)
"""

async def main() -> None:
    from backend.tools.sandbox.pool import sandbox_pool
    print("Warming sandbox pool...")
    await sandbox_pool.warm()

    print("Starting iterative_fix pipeline...\n")
    started = perf_counter()

    result = await iterative_fix(CODE, "test_code.py", max_iterations=6)
    elapsed = (perf_counter() - started) * 1000

    print(f"status={result.status}  bugs_fixed={result.bugs_fixed}  "
          f"iterations={result.total_iterations}  ({elapsed:.0f}ms)\n")

    for step in result.steps:
        mark = "✓ FIXED" if step.fixed else "✗ STUCK"
        print(f"  [{step.iteration}] {mark}  {step.error_type} @ line {step.error_line}")
        if step.detail:
            print(f"         → {step.detail[:200]}")

    print("\n=== FINAL CODE ===")
    print(result.final_code)

    await llm_client.aclose()
    await sandbox_pool.drain()


if __name__ == "__main__":
    asyncio.run(main())

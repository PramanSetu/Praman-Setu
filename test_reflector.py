import asyncio
from backend.orchestrator.state import PipelineState, ReflectorDecision, ValidatorReport, GateResult, ProcessedInput, DetectionMethod, LanguageDetection, ContextPackage, DiagnoserOutput, Hypothesis
from backend.agents.reflector import ReflectorAgent
from backend.llm.client import LLMClient

async def test_reflector():
    # Setup state dummy
    state = PipelineState(
        raw_input=ProcessedInput(
            language="python",
            detection=LanguageDetection(language="python", confidence=1.0, method=DetectionMethod.EXTENSION, reason="test"),
            filename=None, code="def foo(): pass", line_count=2, supplied_error_message=False, error_message="", error_type=None, error_line=None, raw_stderr="", fast_path_eligible=False, execution=None, status="ready"
        ),
        language="python",
        retry_count=1,
        hypothesis_used="H1",
        failed_hypotheses=["H1"],
        diagnoser_output=DiagnoserOutput(
            root_cause="test",
            hypotheses=[
                Hypothesis(id="H1", theory="t1", confidence=0.8, fix_direction="f1"),
                Hypothesis(id="H2", theory="t2", confidence=0.6, fix_direction="f2"),
                Hypothesis(id="H3", theory="t3", confidence=0.4, fix_direction="f3")
            ],
            generated_test="test()"
        ),
        validator_report=ValidatorReport(
            overall_passed=False,
            gate_results={"gate_2": GateResult(passed=False, error="mypy issue", duration_s=0.1)},
            safety_diff=None,
            summary="Failed",
            detailed_failures=["Gate 2 Mypy failed: missing parameter types"]
        )
    )
    
    agent = ReflectorAgent(LLMClient())
    try:
        response = await agent.reflect(state)
        print("Reflector output:")
        print(response.model_dump_json(indent=2))
        assert response.strategy == "escalate_h2" or response.strategy == "escalate_h3" or response.strategy == "refine_current", "Unexpected strategy"
        print("TEST PASSED")
    except Exception as e:
        print("TEST FAILED:", e)

asyncio.run(test_reflector())

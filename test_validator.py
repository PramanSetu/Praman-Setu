import asyncio
from backend.orchestrator.state import ContextPackage, PatcherOutput, DiagnoserOutput
from backend.tools.validator import run_validator

async def main():
    original = "def foo():\n    pass\n"
    bad_syntax_diff = """--- orig.py
+++ patched.py
@@ -1,2 +1,2 @@
 def foo():
-    pass
+    if True pass # SYNTAX ERROR
"""
    ctx = ContextPackage(
        error_node=original,
        function_signature="def foo():",
        imports=[],
        runtime_trace={},
        language="python"
    )
    po = PatcherOutput(unified_diff=bad_syntax_diff, confidence=1.0, approach="bad")
    do = DiagnoserOutput(
        root_cause="none", 
        hypotheses=[{"id":"H1","theory":"t","confidence":1.0,"fix_direction":"f"}]*3, 
        generated_test="def test_foo():\n    foo()\n"
    )
    
    import time
    t0 = time.time()
    rep = await run_validator(po, ctx, do)
    t1 = time.time()
    
    print(f"Gate 1 passed: {rep.gate_results['gate_1'].passed}, elapsed: {t1-t0:.3f}s")
    if rep.overall_passed:
        print("Test 1 FAILED (should not pass overall)")
    else:
        print("Test 1 OK")

asyncio.run(main())

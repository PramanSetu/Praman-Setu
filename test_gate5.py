import asyncio
from backend.orchestrator.state import ContextPackage, PatcherOutput, DiagnoserOutput
from backend.tools.validator import run_validator

async def main():
    original = "import subprocess\ndef foo(cmd):\n    subprocess.run(cmd)\n"
    security_risk_diff = """--- orig.py
+++ patched.py
@@ -1,3 +1,3 @@
 import subprocess
 def foo(cmd):
-    subprocess.run(cmd)
+    subprocess.run(cmd, shell=True)
"""
    ctx = ContextPackage(
        error_node=original,
        function_signature="def foo(cmd):",
        imports=["import subprocess"],
        runtime_trace={},
        language="python"
    )
    po = PatcherOutput(unified_diff=security_risk_diff, confidence=1.0, approach="security risk")
    do = DiagnoserOutput(
        root_cause="none", 
        hypotheses=[{"id":"H1","theory":"t","confidence":1.0,"fix_direction":"f"}]*3, 
        generated_test="def test_foo():\n    pass\n"
    )
    
    rep = await run_validator(po, ctx, do)
    print("overall:", rep.overall_passed)
    print(rep.detailed_failures)

asyncio.run(main())

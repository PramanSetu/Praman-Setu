import json
import asyncio
from backend.orchestrator.state import SafetyFinding, SafetyDiff
from backend.tools.sandbox.pool import sandbox_pool

def _parse_bandit(output: str) -> list[SafetyFinding]:
    findings = []
    try:
        data = json.loads(output)
        for issue in data.get("results", []):
            findings.append(SafetyFinding(
                rule=issue.get("test_id", "bandit_unknown"),
                severity=issue.get("issue_severity", "LOW").upper(),
                line=issue.get("line_number")
            ))
    except json.JSONDecodeError:
        pass
    return findings

def _parse_semgrep(output: str) -> list[SafetyFinding]:
    findings = []
    try:
        data = json.loads(output)
        for res in data.get("results", []):
            findings.append(SafetyFinding(
                rule=res.get("check_id"),
                severity=str(res.get("extra", {}).get("severity", "LOW")).upper(),
                line=res.get("start", {}).get("line")
            ))
    except json.JSONDecodeError:
        pass
    return findings

async def run_security_scanners(code: str) -> list[SafetyFinding]:
    t3a_task = sandbox_pool.execute(language="python", code=code, cmd=["bandit", "-r", "main.py", "-f", "json"], timeout=10)
    t3b_task = sandbox_pool.execute(language="python", code=code, cmd=["semgrep", "--config=p/security-audit", "main.py", "--json"], timeout=15)
    bandit_res, semgrep_res = await asyncio.gather(t3a_task, t3b_task)
    
    findings = []
    findings.extend(_parse_bandit(bandit_res.stdout))
    findings.extend(_parse_semgrep(semgrep_res.stdout))
    return findings

_ORIG_CACHES = {}

async def get_safety_diff(original_code: str, patched_findings: list[SafetyFinding]) -> SafetyDiff:
    code_hash = hash(original_code)
    if code_hash in _ORIG_CACHES:
        original_findings = _ORIG_CACHES[code_hash]
    else:
        original_findings = await run_security_scanners(original_code)
        _ORIG_CACHES[code_hash] = original_findings
        
    orig_set = {(f.rule, f.severity) for f in original_findings}
    new_set = {(f.rule, f.severity) for f in patched_findings}
    
    introduced_tuples = new_set - orig_set
    fixed_tuples = orig_set - new_set
    
    introduced = [SafetyFinding(rule=r, severity=s, line=None) for r, s in introduced_tuples]
    fixed = [SafetyFinding(rule=r, severity=s, line=None) for r, s in fixed_tuples]
    
    has_high_med = any(f.severity in ["HIGH", "MEDIUM", "ERROR"] for f in introduced)
    
    if has_high_med:
        verdict = "regression"
    elif not introduced and fixed:
        verdict = "improvement"
    elif not introduced and not fixed:
        verdict = "neutral"
    else:
        verdict = "tradeoff"
        
    return SafetyDiff(
        introduced=introduced,
        fixed=fixed,
        verdict=verdict
    )

"""Security scanning + diff-regression (Validator Gate 3 + Gate 5 support).

Runs scanners inside the hardened sandbox and computes the before/after safety
delta deterministically.

NOTE on Semgrep: the architecture calls for Bandit + Semgrep, but Semgrep's
`p/security-audit` config downloads rules from the network, and the sandbox runs
with `--network=none`. Running it there silently fails. So Phase 1 uses Bandit
only; offline-bundled Semgrep rules are deferred (see FINAL_ARCHITECTURE.md §9.1).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from backend.orchestrator.state import SafetyDiff, SafetyFinding
from backend.tools.sandbox.pool import sandbox_pool

_HIGH_RISK = {"HIGH", "MEDIUM", "ERROR"}


@dataclass(frozen=True)
class ScanResult:
    findings: list[SafetyFinding]
    errors: list[str] = field(default_factory=list)


def _parse_bandit(output: str) -> list[SafetyFinding]:
    findings: list[SafetyFinding] = []
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return findings
    for issue in data.get("results", []):
        findings.append(
            SafetyFinding(
                rule=issue.get("test_id", "bandit_unknown"),
                severity=str(issue.get("issue_severity", "LOW")).upper(),
                line=issue.get("line_number"),
            )
        )
    return findings


async def scan_code(code: str) -> ScanResult:
    """Run the security scanners on `code` inside the sandbox."""
    res = await sandbox_pool.execute(
        language="python",
        code=code,
        cmd=["bandit", "-r", "main.py", "-f", "json"],
        timeout=10,
    )
    findings = _parse_bandit(res.stdout)
    errors: list[str] = []
    # Bandit prints JSON even when it finds issues; empty stdout means it failed.
    if not res.stdout.strip():
        detail = (res.stderr or "no output").strip()[:300]
        errors.append(f"bandit produced no JSON: {detail}")
    return ScanResult(findings=findings, errors=errors)


def has_high_risk(findings: list[SafetyFinding]) -> bool:
    return any(f.severity in _HIGH_RISK for f in findings)


def compute_safety_diff(
    original: list[SafetyFinding],
    patched: list[SafetyFinding],
) -> SafetyDiff:
    """Deterministic before/after delta of security findings."""
    orig_set = {(f.rule, f.severity) for f in original}
    new_set = {(f.rule, f.severity) for f in patched}

    introduced = [SafetyFinding(rule=r, severity=s, line=None) for r, s in (new_set - orig_set)]
    fixed = [SafetyFinding(rule=r, severity=s, line=None) for r, s in (orig_set - new_set)]

    verdict: Literal["improvement", "neutral", "regression", "tradeoff"]
    if has_high_risk(introduced):
        verdict = "regression"
    elif not introduced and fixed:
        verdict = "improvement"
    elif not introduced and not fixed:
        verdict = "neutral"
    else:
        verdict = "tradeoff"

    return SafetyDiff(introduced=introduced, fixed=fixed, verdict=verdict)


# Original-code scans don't change within a session; cache by content.
_ORIG_CACHE: dict[int, list[SafetyFinding]] = {}


async def safety_diff_against_original(
    original_code: str,
    patched_findings: list[SafetyFinding],
) -> SafetyDiff:
    code_hash = hash(original_code)
    if code_hash not in _ORIG_CACHE:
        _ORIG_CACHE[code_hash] = (await scan_code(original_code)).findings
    return compute_safety_diff(_ORIG_CACHE[code_hash], patched_findings)

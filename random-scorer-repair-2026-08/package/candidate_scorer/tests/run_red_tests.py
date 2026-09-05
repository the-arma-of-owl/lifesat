#!/usr/bin/env python3
"""Dual-target Task-3 gate.

Target 1 - `current`   : analysis/score.py           -> every defect test must be RED
Target 2 - `reference` : tests/reference_scorer.py   -> the SAME tests must be GREEN

Target 1 alone would not prove the suite is satisfiable: a test that can never
pass is worthless as a regression gate. Target 2 proves each defect test becomes
GREEN once the scorer implements the contract, so the suite is a real gate rather
than a permanent failure.

Categories:
  PRECONDITION (`test_precondition_*`) - contract/oracle self-checks; must pass
                                          on BOTH targets.
  DEFECT       (everything else)        - RED on `current`, GREEN on `reference`.
"""
import io
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MODULES = [
    "test_red_01_a3_identity",
    "test_red_02_families",
    "test_red_03_effect_window",
    "test_red_04_d2_native_unit",
    "test_red_05_a4_accounting",
    "test_red_06_f4_evidence",
    "test_red_08_aggregation",
    "test_red_09_output_schema",
]

DEFECT_RE = re.compile(r"CONTRACT DEFECT ([A-Z0-9\-/]+) - (.+)")
FORBIDDEN = [
    (re.compile(r"assertNotEqual\(\s*(\w+)\s*,\s*\1\s*[,)]"), "x != x self-comparison"),
    (re.compile(r"assert(?:In|Equal)\([^,]+,\s*\{\}\s*[,)]"), "literal empty container"),
    (re.compile(r"assertIn\(\s*\"[^\"]+\"\s*,\s*\{\}\s*,"), "assertIn against {}"),
]


def run_one(target):
    """Run the suite in a subprocess against one target; return per-test rows."""
    env = dict(os.environ, LIFESAT_RED_TARGET=target)
    helper = os.path.join(HERE, "_run_one_target.py")
    p = subprocess.run([sys.executable, helper], capture_output=True, text=True,
                       env=env, cwd=HERE)
    if not p.stdout.strip():
        raise SystemExit("target %s could not run (exit %d):\n%s"
                         % (target, p.returncode, p.stderr[-3000:]))
    raw = json.loads(p.stdout.strip().splitlines()[-1])
    rows = []
    for n in raw["all"]:
        if n in raw["errors"]:
            status, msg = "ERROR", raw["errors"][n]
        elif n in raw["failures"]:
            status, msg = "FAIL", raw["failures"][n]
        else:
            status, msg = "PASS", ""
        m = DEFECT_RE.search(msg) if msg else None
        rows.append({"test": n, "status": status,
                     "diagnosed": "%s - %s" % (m.group(1), m.group(2)) if m else None,
                     "kind": "PRECONDITION" if "test_precondition_" in n else "DEFECT"})
    return rows


def lint_sources():
    """No defect test may manufacture its own failure."""
    hits = []
    for fn in sorted(os.listdir(HERE)):
        if not fn.startswith("test_red_"):
            continue
        text = open(os.path.join(HERE, fn), encoding="utf-8").read()
        for rx, label in FORBIDDEN:
            for m in rx.finditer(text):
                hits.append("%s: %s -> %s" % (fn, label, m.group(0)[:60]))
    return hits


def main():
    cur = {r["test"]: r for r in run_one("current")}
    ref = {r["test"]: r for r in run_one("reference")}
    names = sorted(set(cur) | set(ref))

    rows = []
    for n in names:
        c, r = cur.get(n), ref.get(n)
        kind = (c or r)["kind"]
        if kind == "PRECONDITION":
            ok = c["status"] == "PASS" and r["status"] == "PASS"
        else:
            ok = (c["status"] == "FAIL" and c["diagnosed"]
                  and r["status"] == "PASS")
        rows.append({"test": n, "kind": kind, "current": c["status"],
                     "reference": r["status"], "diagnosed": c["diagnosed"],
                     "as_required": bool(ok)})

    dfc = [x for x in rows if x["kind"] == "DEFECT"]
    pre = [x for x in rows if x["kind"] == "PRECONDITION"]
    lint = lint_sources()
    verdict = "GREEN" if all(x["as_required"] for x in rows) and not lint else "RED"

    print(json.dumps({
        "targets": {"current": "analysis/score.py (pre-correction)",
                    "reference": "analysis/tests/reference_scorer.py (contract-conformant)"},
        "total_tests": len(rows),
        "preconditions": {"count": len(pre),
                          "pass_on_both": sum(1 for x in pre if x["as_required"])},
        "defect_tests": {
            "count": len(dfc),
            "red_on_current_with_diagnosis": sum(
                1 for x in dfc if x["current"] == "FAIL" and x["diagnosed"]),
            "green_on_reference": sum(1 for x in dfc if x["reference"] == "PASS"),
            "false_red_current_passes": [x["test"] for x in dfc
                                         if x["current"] == "PASS"],
            "undiagnosed_current_failures": [x["test"] for x in dfc
                                             if x["current"] == "FAIL"
                                             and not x["diagnosed"]],
            "unsatisfiable_reference_failures": [x["test"] for x in dfc
                                                 if x["reference"] != "PASS"],
            "errors": [x["test"] for x in dfc
                       if "ERROR" in (x["current"], x["reference"])],
        },
        "forbidden_construct_lint": lint,
        "diagnosed_defects": sorted({x["diagnosed"] for x in dfc if x["diagnosed"]}),
        "rows": rows,
        "gate": verdict,
    }, indent=2, ensure_ascii=False))
    return 0 if verdict == "GREEN" else 1


if __name__ == "__main__":
    sys.exit(main())

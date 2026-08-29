#!/usr/bin/env python3
"""Task-4 gate: the same suite must now be GREEN on BOTH targets.

  current   -> analysis/score.py            (corrected production scorer)
  reference -> analysis/tests/reference_scorer.py

Task 3 proved the suite was satisfiable and reproduced 30 diagnosed defects on
the pre-correction scorer; that historical evidence lives in run_red_tests.py and
is untouched. This gate asserts the opposite end state and additionally proves
the correction was not obtained by editing the tests or by importing the oracle
into production code.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.dirname(HERE)
SIM = os.path.dirname(ANALYSIS)
sys.path.insert(0, HERE)

# Files the correction was forbidden to touch, with the digests recorded at the
# end of Task 3. A mismatch means the tests or the oracle were edited to pass.
FROZEN_TEST_ASSETS = [
    "contract_oracle.py", "reference_scorer.py", "red_common.py",
    "_run_one_target.py", "run_red_tests.py",
    "test_red_01_a3_identity.py", "test_red_02_families.py",
    "test_red_03_effect_window.py", "test_red_04_d2_native_unit.py",
    "test_red_05_a4_accounting.py", "test_red_06_f4_evidence.py",
    "test_red_08_aggregation.py", "test_red_09_output_schema.py",
]
BASELINE_PATH = os.path.join(HERE, "task3_asset_digests.json")

PRODUCTION_FILES = [os.path.join(ANALYSIS, "score.py")] + [
    os.path.join(ANALYSIS, "scoring", n)
    for n in sorted(os.listdir(os.path.join(ANALYSIS, "scoring")))
    if n.endswith(".py")]

FORBIDDEN_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+.*\b(contract_oracle|reference_scorer)\b", re.M)

# Task-4 regression modules: they exercise the corrected production scorer
# directly (constructed fixtures), so they are not target-agnostic and run only
# against `current`. reference_scorer.py is a frozen Task-3 asset.
TASK4_MODULES = ["test_green_01_f4_counter"]


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def run_one(target):
    env = dict(os.environ, LIFESAT_RED_TARGET=target)
    p = subprocess.run([sys.executable, os.path.join(HERE, "_run_one_target.py")],
                       capture_output=True, text=True, env=env, cwd=HERE)
    if not p.stdout.strip():
        raise SystemExit("target %s could not run (exit %d):\n%s"
                         % (target, p.returncode, p.stderr[-3000:]))
    raw = json.loads(p.stdout.strip().splitlines()[-1])
    rows = []
    for n in raw["all"]:
        if n in raw["errors"]:
            status = "ERROR"
        elif n in raw["failures"]:
            status = "FAIL"
        else:
            status = "PASS"
        rows.append({"test": n, "status": status,
                     "kind": "PRECONDITION" if "test_precondition_" in n else "DEFECT",
                     "detail": (raw["failures"].get(n) or raw["errors"].get(n) or
                                "").strip().splitlines()[-1:] })
    return rows


def run_task4_regression():
    """Run the Task-4 regression modules against the production scorer."""
    import unittest
    loader = unittest.TestLoader()
    rows = []
    for module in TASK4_MODULES:
        p = subprocess.run(
            [sys.executable, "-m", "unittest", module, "-v"],
            capture_output=True, text=True, cwd=HERE,
            env=dict(os.environ, LIFESAT_RED_TARGET="current"))
        passed = p.stderr.count(" ... ok")
        failed = p.stderr.count(" ... FAIL") + p.stderr.count(" ... ERROR")
        rows.append({"module": module, "passed": passed, "failed": failed,
                     "ok": failed == 0 and passed > 0,
                     "tail": p.stderr.strip().splitlines()[-1] if p.stderr else ""})
    return rows


def check_no_oracle_import():
    hits = []
    for path in PRODUCTION_FILES:
        text = open(path, encoding="utf-8").read()
        for m in FORBIDDEN_IMPORT.finditer(text):
            hits.append("%s: %s" % (os.path.relpath(path, SIM), m.group(0).strip()))
    return hits


def check_test_assets_unmodified():
    current = {n: sha256(os.path.join(HERE, n)) for n in FROZEN_TEST_ASSETS}
    if not os.path.exists(BASELINE_PATH):
        with open(BASELINE_PATH, "w", encoding="utf-8") as fh:
            json.dump(current, fh, indent=2, sort_keys=True)
            fh.write("\n")
        return [], current, "baseline recorded"
    baseline = json.load(open(BASELINE_PATH, encoding="utf-8"))
    drift = ["%s: %s != %s" % (n, current[n][:16], baseline.get(n, "absent")[:16])
             for n in FROZEN_TEST_ASSETS if current[n] != baseline.get(n)]
    return drift, current, "verified against baseline"


def main():
    cur = {r["test"]: r for r in run_one("current")}
    ref = {r["test"]: r for r in run_one("reference")}
    names = sorted(set(cur) | set(ref))
    rows = [{"test": n, "kind": cur[n]["kind"], "current": cur[n]["status"],
             "reference": ref[n]["status"],
             "as_required": cur[n]["status"] == "PASS" and ref[n]["status"] == "PASS"}
            for n in names]

    oracle_imports = check_no_oracle_import()
    drift, digests, mode = check_test_assets_unmodified()
    task4 = run_task4_regression()
    defects = [r for r in rows if r["kind"] == "DEFECT"]
    verdict = ("GREEN" if all(r["as_required"] for r in rows)
               and all(t["ok"] for t in task4)
               and not oracle_imports and not drift else "RED")

    print(json.dumps({
        "targets": {"current": "analysis/score.py (corrected)",
                    "reference": "analysis/tests/reference_scorer.py"},
        "total_tests": len(rows),
        "defect_tests": {"count": len(defects),
                         "green_on_current": sum(1 for r in defects
                                                 if r["current"] == "PASS"),
                         "green_on_reference": sum(1 for r in defects
                                                   if r["reference"] == "PASS"),
                         "not_green": [r["test"] for r in rows
                                       if not r["as_required"]]},
        "task4_regression": {"modules": task4,
                             "passed": sum(t["passed"] for t in task4),
                             "failed": sum(t["failed"] for t in task4)},
        "production_files": [os.path.relpath(p, SIM) for p in PRODUCTION_FILES],
        "forbidden_oracle_imports": oracle_imports,
        "test_asset_integrity": {"mode": mode, "drift": drift,
                                 "digests": digests},
        "rows": rows,
        "gate": verdict,
    }, indent=2, ensure_ascii=False))
    return 0 if verdict == "GREEN" else 1


if __name__ == "__main__":
    sys.exit(main())

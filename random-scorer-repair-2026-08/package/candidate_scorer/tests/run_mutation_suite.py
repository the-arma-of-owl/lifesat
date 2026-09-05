#!/usr/bin/env python3
"""Task-5 mutation suite: fail-closed detection of semantic regressions.

For every mutant the harness copies the scorer into a throwaway directory,
applies ONE textual edit to the copy, and runs the gate there in a subprocess.
The live production tree is never modified: it is only ever read.

A mutant counts as CAUGHT only when

  * the gate turns RED, and
  * at least one of the diagnostics the mutation was expected to trip actually
    fails (a mutant killed by an unrelated test does NOT count), and
  * no test errored with a bare traceback.

Negative controls must leave the gate GREEN.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.dirname(HERE)
SIM = os.path.dirname(ANALYSIS)
sys.path.insert(0, HERE)

from mutations import MUTANTS, NEGATIVE_CONTROLS  # noqa: E402

SCORING = os.path.join(ANALYSIS, "scoring")
FORBIDDEN_IMPORT_MARKERS = ("contract_oracle", "reference_scorer")


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def live_digest():
    parts = [os.path.join(ANALYSIS, "score.py")]
    parts += [os.path.join(SCORING, n) for n in sorted(os.listdir(SCORING))
              if n.endswith(".py")]
    return {os.path.relpath(p, SIM): sha256(p) for p in parts}


def build_sandbox(root):
    """A minimal simulation tree whose scorer can be mutated safely."""
    os.makedirs(os.path.join(root, "analysis"))
    shutil.copy2(os.path.join(ANALYSIS, "score.py"),
                 os.path.join(root, "analysis", "score.py"))
    shutil.copytree(SCORING, os.path.join(root, "analysis", "scoring"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(HERE, os.path.join(root, "analysis", "tests"),
                    ignore=shutil.ignore_patterns("__pycache__",
                                                  "task3_asset_digests.json"))
    # Read-only inputs are shared by symlink: they are never written.
    os.symlink(os.path.join(SIM, "results"), os.path.join(root, "results"))
    os.symlink(os.path.join(SIM, "specs"), os.path.join(root, "specs"))
    return root


def apply_edit(root, spec):
    if spec.get("file") is None:
        return True, "no edit"
    path = os.path.join(root, "analysis", spec["file"])
    text = open(path, encoding="utf-8").read()
    if spec["old"] not in text:
        return False, "anchor not found in %s" % spec["file"]
    if text.count(spec["old"]) != 1:
        return False, "anchor is not unique in %s (%d matches)" % (
            spec["file"], text.count(spec["old"]))
    open(path, "w", encoding="utf-8").write(text.replace(spec["old"], spec["new"], 1))
    return True, "applied"


def run_gate(root):
    """Run the frozen suite (current target) plus the Task-4 regression."""
    tests = os.path.join(root, "analysis", "tests")
    env = dict(os.environ, LIFESAT_RED_TARGET="current")
    out = {"failures": {}, "errors": {}, "all": [], "crashed": None}

    p = subprocess.run([sys.executable, os.path.join(tests, "_run_one_target.py")],
                       capture_output=True, text=True, env=env, cwd=tests)
    if not p.stdout.strip():
        out["crashed"] = (p.stderr or "")[-1500:]
        return out
    raw = json.loads(p.stdout.strip().splitlines()[-1])
    out["all"] = list(raw["all"])
    out["failures"].update(raw["failures"])
    out["errors"].update(raw["errors"])

    q = subprocess.run([sys.executable,
                        os.path.join(tests, "_run_task45_modules.py")],
                       capture_output=True, text=True, env=env, cwd=tests)
    if not q.stdout.strip():
        out["crashed"] = ((out["crashed"] or "") + (q.stderr or ""))[-1500:]
        return out
    raw2 = json.loads(q.stdout.strip().splitlines()[-1])
    out["all"] += list(raw2["all"])
    out["failures"].update(raw2["failures"])
    out["errors"].update(raw2["errors"])
    return out


def scan_forbidden_imports(root):
    hits = []
    files = [os.path.join(root, "analysis", "score.py")]
    scoring = os.path.join(root, "analysis", "scoring")
    files += [os.path.join(scoring, n) for n in sorted(os.listdir(scoring))
              if n.endswith(".py")]
    for path in files:
        for line in open(path, encoding="utf-8"):
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            if any(m in stripped for m in FORBIDDEN_IMPORT_MARKERS):
                hits.append("%s: %s" % (os.path.basename(path), stripped))
    return hits


WRAPPED_MARKERS = ("raised TypeError", "raised KeyError", "raised AttributeError",
                   "raised IndexError", "raised ValueError", "raised NameError",
                   "raised ZeroDivisionError",
                   "During handling of the above exception",
                   "The above exception was the direct cause")


def short(name):
    return name.split(".")[-1]


def wrapped_exceptions(result):
    """Failures caused by an exception, however it was wrapped.

    A unittest failure message always ends in a traceback, so the presence of the
    word `Traceback` proves nothing. What matters is the FINAL exception line: a
    plain `AssertionError` is a diagnosis, anything else is a crash. Helpers that
    convert a throw into `self.fail("... raised TypeError: ...")` are caught by
    the explicit markers, and chained exceptions by the `During handling` banner.
    """
    hits = []
    for name, msg in (list(result["failures"].items())
                      + list(result["errors"].items())):
        text = msg if isinstance(msg, str) else ""
        if any(marker in text for marker in WRAPPED_MARKERS):
            hits.append(short(name))
            continue
        finals = [line.strip() for line in text.splitlines()
                  if re.match(r"^[A-Za-z_][A-Za-z0-9_.]*(Error|Exception)\b", line.strip())]
        if finals and not finals[-1].startswith("AssertionError"):
            hits.append(short(name))
    return sorted(set(hits))


def evaluate(spec, result, imports, is_control, baseline=frozenset()):
    failed = {short(n) for n in result["failures"]}
    errored = {short(n) for n in result["errors"]}
    wrapped = wrapped_exceptions(result)
    crashed = result["crashed"] is not None
    gate_red = bool(failed or errored or crashed or imports)

    row = {"id": spec["id"], "symbol": spec.get("symbol"),
           "gate": "RED" if gate_red else "GREEN",
           "failed_tests": sorted(failed), "errored_tests": sorted(errored),
           "wrapped_exceptions": wrapped,
           "traceback": bool(errored) or crashed or bool(wrapped),
           "forbidden_imports": imports}

    new_failures = sorted(failed - set(baseline))
    row["new_failures"] = new_failures
    row["baseline_failures"] = sorted(failed & set(baseline))

    if is_control:
        row["expected"] = "no NEW failure beyond the mutation-free baseline"
        row["observed"] = ("clean" if not new_failures
                           else "new failures: %s" % new_failures)
        row["as_required"] = (not new_failures and not row["traceback"]
                              and not imports)
        return row

    if "expect_gate" in spec:
        row["expected"] = "gate check `%s` trips" % spec["expect_gate"]
        row["observed"] = ("forbidden_imports=%r" % imports if imports
                           else "gate check did not trip")
        row["as_required"] = bool(imports) and not crashed
        return row

    wanted = set(spec["expect_any"])
    # A diagnostic that already fails without the mutation proves nothing.
    hit = sorted((wanted & failed) - set(baseline))
    marker = spec.get("expect_marker")
    marker_seen = True
    if marker:
        marker_seen = any(marker in (result["failures"].get(n) or "")
                          for n in result["failures"] if short(n) in wanted)
    row["expected"] = "one of %s newly fails%s" % (
        sorted(wanted), " carrying %r" % marker if marker else "")
    if not hit:
        row["observed"] = "only unrelated: %s" % sorted(failed - wanted)
    elif not marker_seen:
        row["observed"] = ("intended test failed but without the diagnostic "
                           "marker %r: %s" % (marker, hit))
    else:
        row["observed"] = "intended: %s" % hit
    row["as_required"] = (bool(hit) and marker_seen and not errored
                          and not crashed and not wrapped)
    return row


def main():
    before = live_digest()

    # Mutation-free baseline: whatever already fails without any edit is not
    # attributable to a mutant and must not be counted as a kill.
    base_root = tempfile.mkdtemp(prefix="lifesat-base-")
    try:
        build_sandbox(base_root)
        base_result = run_gate(base_root)
        baseline = frozenset(short(n) for n in base_result["failures"])
        baseline_errors = sorted(short(n) for n in base_result["errors"])
    finally:
        shutil.rmtree(base_root, ignore_errors=True)

    rows = []
    for spec, is_control in ([(m, False) for m in MUTANTS] +
                             [(c, True) for c in NEGATIVE_CONTROLS]):
        root = tempfile.mkdtemp(prefix="lifesat-mut-")
        try:
            build_sandbox(root)
            ok, note = apply_edit(root, spec)
            if not ok:
                rows.append({"id": spec["id"], "symbol": spec.get("symbol"),
                             "gate": "N/A", "expected": "edit applies",
                             "observed": note, "as_required": False,
                             "traceback": False, "failed_tests": [],
                             "errored_tests": [], "forbidden_imports": []})
                continue
            result = run_gate(root)
            imports = scan_forbidden_imports(root)
            rows.append(evaluate(spec, result, imports, is_control, baseline))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    after = live_digest()
    real = [r for r in rows if not r["id"].startswith("NC")]
    controls = [r for r in rows if r["id"].startswith("NC")]
    verdict = ("GREEN" if all(r["as_required"] for r in rows) and before == after
               else "RED")

    print(json.dumps({
        "mutants": {"count": len(real),
                    "caught_for_the_intended_reason":
                        sum(1 for r in real if r["as_required"]),
                    "survived_or_wrong_reason":
                        [r["id"] for r in real if not r["as_required"]],
                    "with_traceback": [r["id"] for r in real if r["traceback"]],
                    "wrapped_exceptions": {r["id"]: r["wrapped_exceptions"]
                                           for r in real
                                           if r.get("wrapped_exceptions")}},
        "negative_controls": {"count": len(controls),
                              "green": sum(1 for r in controls if r["as_required"]),
                              "unexpectedly_red":
                                  [r["id"] for r in controls
                                   if not r["as_required"]]},
        "mutation_free_baseline": {"failures": sorted(baseline),
                                   "errors": baseline_errors},
        "live_scorer_unchanged": before == after,
        "live_scorer_digests": after,
        "rows": rows,
        "gate": verdict,
    }, indent=2, ensure_ascii=False))
    return 0 if verdict == "GREEN" else 1


if __name__ == "__main__":
    sys.exit(main())

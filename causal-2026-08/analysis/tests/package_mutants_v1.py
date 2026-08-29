#!/usr/bin/env python3
"""PM1-PM5 -- the corrected package's completeness guards are not tautologies.

Each mutant disables ONE of the Task-7 completeness fixes in a COPY of the tree,
rebuilds the package there, and asserts the intended test turns RED.

The scorer digest pin is re-derived inside each sandbox before building: the pin
exists to stop an unnoticed scorer swap in production, and leaving it stale here
would make every mutant fail on the pin instead of on the semantics under test.

Run standalone:  python3 analysis/tests/package_mutants_v1.py
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.dirname(HERE)
SIM = os.path.dirname(ANALYSIS)
BUILDER = "analysis/build_corrected_package_v1.py"
SHARED = ("specs", "results", "results-v2-iss06", "src", "out", "simulations")

MUTANTS = [
 {"id": "PM1", "file": "analysis/build_corrected_package_v1.py",
  "guard": "EST-A4-L2-02 per-subtype split",
  "old": '''    "EST-A4-L2-02": lambda r: {
        "modification_detection_rate": (''',
  "new": '''    "EST-A4-L2-02-REMOVED": lambda r: {
        "modification_detection_rate": (''',
  "must_fail": ["test_40_rescore_coverage_requires_real_output",
                "test_a4_subtype_split_exists_and_never_double_credits",
                "test_every_rescore_estimand_is_produced"]},

 {"id": "PM2", "file": "analysis/scoring/families.py",
  "guard": "one alarm may credit only one subtype",
  "old": '''        detected[key] += 1''',
  "new": '''        detected["modification"] += 1
        detected["delay"] += 1''',
  # Double-crediting is now refused by the production partition guard, so the
  # expected outcome is a fail-closed BUILD refusal carrying that diagnostic,
  # not a package that is built and then rejected by a test.
  "expect_build_refusal": "accounts for",
  "must_fail": []},

 {"id": "PM3", "file": "analysis/scoring/windows.py",
  "guard": "drop alarm-covered numerator",
  "old": '''            if window in alarm_windows:
                covered += 1''',
  "new": '''            if False:
                covered += 1''',
  "must_fail": ["test_l3_02_publishes_the_alarm_covered_numerator"]},

 {"id": "PM6", "file": "analysis/scoring/families.py",
  "guard": "D3 no-decision-opportunity must not be a D2 window class",
  "old": '''        "no_decision_opportunity": actions["drop"],''',
  "new": '''        "no_decision_opportunity": 1,''',
  "must_fail": ["test_d3_no_decision_opportunity_is_every_drop",
                "test_the_d3_figure_is_not_borrowed_from_the_d2_split"]},

 {"id": "PM7", "file": "analysis/scoring/families.py",
  "guard": "partition equality: an orphan credit must not be tolerated",
  # Relaxing != to > alone is a no-op on healthy data, so this mutant also
  # drops a credit: the check is weakened AND a credited effect event is lost.
  "old": '''        detected[key] += 1

    total = detected["modification"] + detected["delay"]
    if total != len(credited):''',
  "new": '''        if key == "delay":
            continue
        detected[key] += 1

    total = detected["modification"] + detected["delay"]
    if total > len(credited):''',
  "must_fail": ["test_the_builders_own_validation_is_green"]},

 {"id": "PM4", "file": "analysis/build_corrected_package_v1.py",
  "guard": "EST-A4-L3-01 needs no subtype split",
  "old": "UNSUPPORTED = {}",
  "new": ('UNSUPPORTED = {"EST-A4-L3-01": "wrongly declared to require a '
          'per-subtype split"}'),
  "must_fail": ["test_no_estimand_is_left_unsupported",
                "test_no_rescore_estimand_is_unsupported_tier2_or_placeholder"]},

 {"id": "PM5", "file": "analysis/build_corrected_package_v1.py",
  "guard": "F5/F6 are produced, not placeholders",
  "old": '''            "inventory": [a["run"] for a in A6S_ARMS], "runs": rows}''',
  "new": '''            "inventory": [a["run"] for a in A6S_ARMS], "runs": []}''',
  "must_fail": ["test_no_rescore_estimand_is_unsupported_tier2_or_placeholder",
                "test_tier2_f5_and_f6_are_produced_and_quarantined",
                "test_40_rescore_coverage_requires_real_output"]},
]

NEGATIVE_CONTROLS = [
 {"id": "NC1", "file": "analysis/scoring/windows.py",
  "guard": "comment-only edit must stay GREEN",
  "old": "            # EST-A4-L3-02: within the native class, was the drop's",
  "new": "            # EST-A4-L3-02 (comment reworded by a negative control):"},
 {"id": "NC2", "file": "analysis/build_corrected_package_v1.py",
  "guard": "docstring-only edit must stay GREEN",
  "old": '"""Task 7 -- versioned corrected result package (contract v1.4.3).',
  "new": '"""Task 7 - versioned corrected result package (contract v1.4.3).'},
]


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


ROUND = os.path.dirname(SIM)


def build_sandbox(root):
    """Mirror the ROUND layout, not just simulation/.

    The builder resolves the fleet verification file relative to the round root,
    so a sandbox that only contains simulation/ makes every build fail on a
    missing input and the tests then skip - which would look like a pass.
    """
    sim = os.path.join(root, "simulation")
    os.makedirs(sim)
    shutil.copytree(ANALYSIS, os.path.join(sim, "analysis"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    for name in SHARED:
        src = os.path.join(SIM, name)
        if os.path.exists(src):
            os.symlink(src, os.path.join(sim, name))
    os.symlink(os.path.join(ROUND, "verification"),
               os.path.join(root, "verification"))
    return sim


def repin_scorer(root):
    """Re-derive the scorer pin inside the sandbox (see module docstring).

    The digest recipe is reproduced here rather than imported, so the harness
    does not execute the very code it is about to mutate.
    """
    analysis = os.path.join(root, "simulation", "analysis")
    parts = [os.path.join(analysis, "score.py")]
    scoring = os.path.join(analysis, "scoring")
    parts += [os.path.join(scoring, n) for n in sorted(os.listdir(scoring))
              if n.endswith(".py")]
    digest = hashlib.sha256()
    for path in parts:
        digest.update(("%s  %s\n" % (sha256(path),
                                      os.path.relpath(path, analysis))
                       ).encode("utf-8"))
    value = digest.hexdigest()
    # Both the builder's pin and the test's pin are sandbox artefacts. Re-pin
    # both, or a comment-only edit to scorer code trips the pin and a negative
    # control looks like a regression. (The pin flagging a comment is CORRECT
    # in production: any scorer byte change must be noticed there.)
    targets = [(os.path.join(root, "simulation", BUILDER), '"scorer": "'),
               (os.path.join(root, "simulation", "analysis", "tests",
                             "test_corrected_package_v1.py"),
                '"scorer_sha256":\n            "')]
    for path, marker in targets:
        text = open(path, encoding="utf-8").read()
        if marker not in text:
            continue
        start = text.index(marker) + len(marker)
        end = text.index('"', start)
        open(path, "w", encoding="utf-8").write(text[:start] + value + text[end:])
    return value


def run_case(spec, apply_edit=True):
    root = tempfile.mkdtemp(prefix="lifesat-pkg-mut-")
    try:
        sim = build_sandbox(root)
        if apply_edit:
            path = os.path.join(sim, spec["file"])
            text = open(path, encoding="utf-8").read()
            if text.count(spec["old"]) != 1:
                return {"anchor": "matched %d times" % text.count(spec["old"]),
                        "failed": set(), "rc": None}
            open(path, "w", encoding="utf-8").write(
                text.replace(spec["old"], spec["new"], 1))
        repin_scorer(root)
        out_dir = os.path.join(root, "pkg")
        build = subprocess.run(
            [sys.executable, os.path.join(sim, BUILDER), "--out", out_dir],
            capture_output=True, text=True, cwd=sim)
        env = dict(os.environ, LIFESAT_PACKAGE=out_dir)
        tests = subprocess.run(
            [sys.executable, "-m", "unittest", "test_corrected_package_v1", "-v"],
            cwd=os.path.join(sim, "analysis", "tests"),
            capture_output=True, text=True, env=env)
        failed = set()
        for line in (tests.stderr or "").splitlines():
            if line.startswith(("FAIL: ", "ERROR: ")):
                failed.add(line.split(": ", 1)[1].split(" ")[0].strip())
        built = os.path.isdir(out_dir)
        return {"anchor": "applied" if apply_edit else "clean",
                "build_rc": build.returncode, "failed": failed,
                "rc": tests.returncode, "package_built": built,
                "build_stderr": (build.stderr or "")[-400:]}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    a = ap.parse_args()
    before = {f: sha256(os.path.join(SIM, f))
              for f in (BUILDER, "analysis/scoring/families.py",
                        "analysis/scoring/windows.py")}

    baseline = run_case(MUTANTS[0], apply_edit=False)
    rows = []
    for spec in MUTANTS:
        if a.only and spec["id"] != a.only:
            continue
        r = run_case(spec)
        if spec.get("expect_build_refusal"):
            # A production guard refusing to build is a STRONGER outcome than a
            # test failure - the bad package never exists - but it counts only
            # when the refusal carries the guard's own diagnostic, so an
            # unrelated crash cannot pass as a catch.
            marker = spec["expect_build_refusal"]
            stderr = r.get("build_stderr") or ""
            rows.append({"id": spec["id"], "guard": spec["guard"],
                         "expected_to_fail": ["<fail-closed build refusal>"],
                         "intended_caught": ([marker]
                                             if marker in stderr else []),
                         "refusal_marker_seen": marker in stderr,
                         "build_rc": r.get("build_rc"),
                         "package_built": r.get("package_built"),
                         "build_stderr": stderr[-200:],
                         "as_required": (r.get("build_rc") not in (0, None)
                                         and not r.get("package_built")
                                         and marker in stderr)})
            continue
        wanted = set(spec["must_fail"])
        caught = sorted(wanted & r["failed"])
        # A mutant that only breaks the BUILD proves nothing about the tests.
        rows.append({"id": spec["id"], "guard": spec["guard"],
                     "expected_to_fail": sorted(wanted),
                     "intended_caught": caught,
                     "actually_failed": sorted(r["failed"]),
                     "anchor": r.get("anchor"),
                     "build_rc": r.get("build_rc"),
                     "package_built": r.get("package_built"),
                     "tests_red": r["rc"] != 0,
                     "build_stderr": r.get("build_stderr", "")[-200:],
                     # The package must still BUILD: a mutant that only crashes
                     # the build proves nothing about the test suite.
                     "as_required": (bool(caught) and r["rc"] != 0
                                     and r.get("package_built"))})
    controls = []
    for spec in NEGATIVE_CONTROLS:
        if a.only and spec["id"] != a.only:
            continue
        r = run_case(spec)
        new_failures = sorted(r["failed"] - baseline["failed"])
        controls.append({"id": spec["id"], "guard": spec["guard"],
                         "new_failures": new_failures,
                         "package_built": r.get("package_built"),
                         "as_required": (not new_failures and r["rc"] == 0
                                         and r.get("package_built"))})

    after = {f: sha256(os.path.join(SIM, f)) for f in before}
    ok = (all(x["as_required"] for x in rows)
          and all(x["as_required"] for x in controls)
          and before == after and not baseline["failed"]
          and baseline.get("package_built"))
    print(json.dumps({"schema": "lifesat-package-mutants/v1",
                      "baseline_clean": (not baseline["failed"]
                                         and baseline.get("package_built")),
                      "baseline_package_built": baseline.get("package_built"),
                      "baseline_failures": sorted(baseline["failed"]),
                      "live_files_unchanged": before == after,
                      "mutants": len(rows),
                      "caught": sum(1 for x in rows if x["as_required"]),
                      "not_caught": [x["id"] for x in rows
                                     if not x["as_required"]],
                      "negative_controls": len(controls),
                      "controls_green": sum(1 for x in controls
                                            if x["as_required"]),
                      "rows": rows, "controls": controls,
                      "gate": "GREEN" if ok else "RED"}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

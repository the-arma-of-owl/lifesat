#!/usr/bin/env python3
"""GM1-GM9 — proof that the fleet driver's guards are not tautologies.

Each mutant disables exactly ONE guard in a COPY of analysis/run_rerun_v2.py and
asserts that the tests written to catch that guard turn RED, and that they do so
for the INTENDED reason (the diagnostic marker), not by collateral damage.

The live driver is opened read-only and its digest is re-checked at the end.
No simulation is executed by any mutant.

Run standalone:   python3 analysis/tests/fleet_guard_mutants_v1.py
Exit code 0 only if every mutant is caught for its intended reason.
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
DRIVER = os.path.join(ANALYSIS, "run_rerun_v2.py")
TEST = os.path.join(HERE, "test_fleet_driver_guards.py")

# Directories the driver reads (authority pins, binary, ini). Shared by symlink:
# the sandbox never writes to them.
SHARED = ("specs", "src", "out", "simulations", "results")

MUTANTS = [
 {"id": "GM1", "guard": "output root existence check",
  "old": '''    if os.path.exists(real):
        raise OutputError("output root %r already exists; refusing to reuse or "
                          "merge into it" % real)''',
  "new": '''    if False:
        raise OutputError("disabled")''',
  "marker": "already exists' not found",  # removing the existence check still trips the FileExistsError fallback, so the intended diagnostic is the WRONG reason, not a missing exception
  "must_fail": ["test_M1_existing_output_root_is_refused",
                "test_a_fresh_root_is_created_atomically_and_then_refuses_reuse"]},

 {"id": "GM2", "guard": "whole plan validation",
  "old": ('def validate_plan(plan):\n'
          '    """Fail closed on anything that is not exactly the authorised fleet."""'),
  "new": ('def validate_plan(plan):\n'
          '    """disabled"""\n'
          '    return plan\n\n'
          'def _dead(plan):'),
  "marker": "PlanError not raised",
  "must_fail": ["test_M2_duplicate_seed_is_refused",
                "test_M3_missing_seed_is_refused",
                "test_M3b_missing_seed_with_the_count_restored_is_still_refused",
                "test_M4_unauthorised_cell_is_refused",
                "test_M5_scenario_cell_mismatch_is_refused"]},

 {"id": "GM3", "guard": "pre-existing output preflight",
  "old": '''    present = [p for p in target_paths(out_dir, identity) if os.path.exists(p)]''',
  "new": '''    present = []''',
  "marker": "OutputError not raised",
  "must_fail": ["test_M6_pre_existing_output_file_is_refused"]},

 {"id": "GM4", "guard": "results-tree destination check",
  "old": '''    if real == OLD_RESULTS or real.startswith(OLD_RESULTS + os.sep):''',
  "new": '''    if False:''',
  "marker": "accepted results tree' not found",  # removing the destination check still trips the existence check, so again the diagnostic is the wrong reason
  "must_fail": ["test_the_accepted_results_tree_is_never_a_destination",
                "test_a_subdirectory_of_the_accepted_tree_is_also_refused"]},

 {"id": "GM5", "guard": "authorised cell set",
  "old": '''AUTHORISED_CELLS = {"A1-D3": "A1", "A2-D3": "A2", "A3-D3": "A3"}''',
  "new": ('AUTHORISED_CELLS = {"A1-D3": "A1", "A2-D3": "A2", "A3-D3": "A3", '
          '"B0-D3": "B0"}'),
  "marker": "B0-D3",
  "must_fail": ["test_b0_d3_is_not_reachable_from_the_fleet",
                "test_only_the_three_contract_cells_appear",
                "test_the_fleet_generates_exactly_180_unique_identities"]},

 {"id": "GM6", "guard": "success criteria",
  "old": '''    ok = (counts["completed"] == EXPECTED_RUNS and counts["failed"] == 0
          and counts["duplicate"] == 0 and counts["missing"] == 0
          and counts["stray"] == 0 and counts["incomplete"] == 0
          and fs["set_matches_expected_exactly"]
          and counts["artefacts_on_disk"] == EXPECTED_RUNS * len(SUFFIXES))''',
  "new": '''    ok = True''',
  "marker": None,
  "must_fail": ["test_a_short_fleet_is_not_success", "test_any_failure_is_not_success",
                "test_a_stray_file_blocks_green_even_when_all_180_completed"]},

 {"id": "GM7", "guard": "stop-on-first-failure scheduling",
  "old": '''        if stop.is_set():
            return ("skipped", run, None)''',
  "new": '''        if False:
            return ("skipped", run, None)''',
  "marker": None,
  "must_fail": ["test_no_new_work_is_launched_after_the_first_failure"]},

 # ── new in v1: the two guards added for the execution gate ───────────────
 {"id": "GM8", "guard": "authority pin verification",
  "old": '''    if problems:
        raise AuthorityError("authority pin mismatch; nothing was created:\\n  - "
                             + "\\n  - ".join(problems))''',
  "new": '''    if False:
        raise AuthorityError("disabled")''',
  "marker": "AuthorityError not raised",
  "must_fail": ["test_a_wrong_hash_is_refused_and_no_output_root_is_created",
                "test_a_missing_pinned_file_is_refused",
                "test_a_wrong_seal_digest_is_refused",
                "test_a_src_tree_change_is_refused_even_if_every_named_file_matches"]},

 {"id": "GM9", "guard": "filesystem stray scan",
  "old": '''    fs = scan_output_dir(out_dir, plan)''',
  "new": '''    fs = {"expected_count": EXPECTED_RUNS * len(SUFFIXES),
          "found_count": len(completed) * len(SUFFIXES),
          "missing": [], "stray": [], "temporary": [],
          "unexpected_directories": [], "incomplete_stems": [],
          "duplicate_stems": [], "set_matches_expected_exactly": True}''',
  "marker": "stray artefact must block GREEN",
  "must_fail": ["test_a_stray_file_blocks_green_even_when_all_180_completed",
                "test_a_temporary_file_is_stray",
                "test_a_wrong_suffix_is_stray",
                "test_an_unexpected_directory_is_stray",
                ("test_a_vanished_artefact_is_caught_even_though_the_driver_"
                 "reported_success")]},
]


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def build_sandbox(root):
    os.makedirs(os.path.join(root, "analysis", "tests"))
    shutil.copy2(DRIVER, os.path.join(root, "analysis", "run_rerun_v2.py"))
    # run_matrix.py is an AUTHORITY-PINNED file, so the sandbox must carry it or
    # the mutation-free baseline fails for a reason unrelated to any mutant.
    shutil.copy2(os.path.join(ANALYSIS, "run_matrix.py"),
                 os.path.join(root, "analysis", "run_matrix.py"))
    shutil.copy2(TEST, os.path.join(root, "analysis", "tests",
                                    "test_fleet_driver_guards.py"))
    for name in SHARED:
        src = os.path.join(SIM, name)
        if os.path.exists(src):
            os.symlink(src, os.path.join(root, name))


def run_tests(root):
    p = subprocess.run([sys.executable, "-m", "unittest",
                        "test_fleet_driver_guards", "-v"],
                       cwd=os.path.join(root, "analysis", "tests"),
                       capture_output=True, text=True)
    text = p.stderr or ""
    failed, messages, current = set(), {}, None
    for line in text.splitlines():
        if line.startswith(("FAIL: ", "ERROR: ")):
            current = line.split(": ", 1)[1].split(" ")[0].strip()
            failed.add(current)
            messages[current] = []
        elif current is not None:
            messages[current].append(line)
    return failed, {k: "\n".join(v) for k, v in messages.items()}, p.returncode


def evaluate(spec, failed, messages, rc):
    wanted = set(spec["must_fail"])
    caught = sorted(wanted & failed)
    collateral = sorted(failed - wanted)
    marker_ok = True
    if spec.get("marker"):
        marker_ok = bool(caught) and any(spec["marker"] in messages.get(name, "")
                                         for name in caught)
    return {"id": spec["id"], "guard": spec["guard"],
            "expected_to_fail": sorted(wanted),
            "intended_caught": caught,
            "collateral_failures": collateral,
            "diagnostic_marker": spec.get("marker"),
            "marker_seen": marker_ok,
            "gate_turned_red": rc != 0,
            "as_required": bool(caught) and marker_ok and rc != 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="run a single mutant id, e.g. GM8")
    a = ap.parse_args()

    before = sha256(DRIVER)
    specs = [m for m in MUTANTS if not a.only or m["id"] == a.only]

    # A mutation-free baseline: whatever fails without any edit is not a kill.
    base = tempfile.mkdtemp(prefix="lifesat-guard-base-")
    try:
        build_sandbox(base)
        base_failed, _msg, base_rc = run_tests(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    rows = []
    for spec in specs:
        root = tempfile.mkdtemp(prefix="lifesat-guard-")
        try:
            build_sandbox(root)
            path = os.path.join(root, "analysis", "run_rerun_v2.py")
            text = open(path, encoding="utf-8").read()
            if text.count(spec["old"]) != 1:
                rows.append({"id": spec["id"], "as_required": False,
                             "note": "anchor matched %d times"
                                     % text.count(spec["old"])})
                continue
            open(path, "w", encoding="utf-8").write(
                text.replace(spec["old"], spec["new"], 1))
            failed, messages, rc = run_tests(root)
            row = evaluate(spec, failed - base_failed, messages, rc)
            rows.append(row)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    after = sha256(DRIVER)
    ok = (all(r.get("as_required") for r in rows) and before == after
          and not base_failed and base_rc == 0)
    out = {"schema": "lifesat-fleet-guard-mutants/v1",
           "driver": os.path.relpath(DRIVER, SIM), "driver_sha256": after,
           "live_driver_unchanged": before == after,
           "baseline": {"failures": sorted(base_failed), "clean": base_rc == 0},
           "mutants": len(rows),
           "caught_for_the_intended_reason":
               sum(1 for r in rows if r.get("as_required")),
           "not_caught": [r["id"] for r in rows if not r.get("as_required")],
           "rows": rows,
           "gate": "GREEN" if ok else "RED"}
    print(json.dumps(out, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

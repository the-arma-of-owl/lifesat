#!/usr/bin/env python3
"""run_phase4_suite.py — RED, GREEN and the owning-mutant corpus.

  RED      the ORIGINAL DEFECT, executed against the real fixture. The old
           `tmSeq` read is run and shown to credit nothing, and the guards
           reject it. This is the plan's "prove old scorer RED for intended
           field mismatch" — proved by running it, not by describing it.
  GREEN    the repaired join binds every alarm in the fixture run, conserves
           every raw row, agrees with the independent time oracle, and the
           registry describes the fields the producer actually emits.
  MUTANTS  every detector in the Phase 4 contract is rejected by at least one
           mutant, by the detector that owns it — including the five the plan
           names: n->tmSeq, ordinal shift, duplicate ordinal, missing
           observation, out-of-range ordinal.

Nothing here writes to the raw corpus, the historical package, the seal, or the
v7 tree. The full-corpus rescoring and invariance proof live in
`validate_phase4.py`; this file is the unit gate.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import p4_authority as PA          # noqa: E402
import p4_checks as PC             # noqa: E402
import p4_mutations as PM          # noqa: E402
import p4_reference_oracle as REF  # noqa: E402

sys.path.insert(0, PA.CANDIDATE_SCORER)
from scoring import rndjoin        # noqa: E402


def red_stage():
    """Run the ORIGINAL defect against the real fixture and reject it."""
    data = PM.fixture()
    events = data["events"]
    legacy = PC._legacy_alarmed(events)                     # noqa: SLF001
    findings = PC.check_join_is_ordinal(events, legacy, PM.FIXTURE_RUN)
    fired = {row["detector_id"] for row in findings}
    raw = sum(1 for row in events if row["cat"] == "rnd.alarm")
    return {
        "detectors_fired": sorted(fired),
        "legacy_credited_observations": len(legacy),
        "outcome": "REFUSED" if "D-P4-JOIN-KEY-01" in fired else "ESCAPED",
        "raw_alarm_rows": raw,
        "stage": "RED",
        "statement": (
            f"the old tmSeq/seq read credits {len(legacy)} observations while "
            f"the run carries {raw} raw alarm rows; it reported zeros instead "
            f"of raising, which is why the defect survived"),
    }


def green_stage():
    """The repaired join on the same real fixture."""
    data = PM.fixture()
    events = data["events"]
    binding = rndjoin.bind(events)
    conservation = binding.conservation
    findings = []
    findings += PC.check_conservation(conservation, events, PM.FIXTURE_RUN)
    findings += PC.check_dispositions(binding, PM.FIXTURE_RUN)
    findings += PC.check_ordinal_health(conservation, PM.FIXTURE_RUN)
    findings += PC.check_time_witness(conservation, PM.FIXTURE_RUN)
    findings += PC.check_join_is_ordinal(events, binding.alarmed_ordinals,
                                         PM.FIXTURE_RUN)
    findings += PC.check_field_registry("rndjoin")
    findings += REF.compare(events, data["scored"]["effect_events"],
                            data["scored"]["F3"]["RND"], binding)
    return {
        "conservation": conservation,
        "findings": findings,
        "oracle_agrees": not any(
            row["detector_id"].startswith("D-P4-ORACLE") for row in findings),
        "scored_confusion": {key: data["scored"]["F3"]["RND"][key]
                             for key in ("tp", "fp", "fn", "tn")},
        "stage": "GREEN",
        "verdict": "GREEN" if not findings else "RED",
    }


def mutant_stage(workdir):
    rows = []
    for name, must_fire, mutate in PM.MUTANTS:
        directory = os.path.join(workdir, name)
        os.makedirs(directory, exist_ok=True)
        try:
            fired = mutate(directory)
        except Exception as error:            # noqa: BLE001 - report, never hide
            rows.append({"detectors_fired": [], "error": str(error)[:300],
                         "must_fire": must_fire, "name": name,
                         "outcome": "ERROR"})
            continue
        rows.append({
            "detectors_fired": sorted(fired),
            "must_fire": must_fire,
            "name": name,
            "outcome": "REJECTED" if must_fire in fired else "ESCAPED",
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(PA.PHASE4_ROOT, "evidence"))
    args = parser.parse_args()

    red = red_stage()
    print(f"RED    {red['outcome']:<9} {red['detectors_fired']}")
    print(f"       {red['statement']}")

    green = green_stage()
    c = green["conservation"]
    print(f"GREEN  {green['verdict']}  {c['raw_alarm_rows']} raw rows == "
          f"{c['matched']} matched + {c['unmatched']} unmatched  "
          f"(exact: {c['exact']}, time-inconsistent: "
          f"{c['matched_time_inconsistent']})")
    print(f"GREEN  independent time oracle agrees: {green['oracle_agrees']}")
    print(f"GREEN  repaired confusion: {green['scored_confusion']}")
    for row in green["findings"]:
        print(f"       RED {row['detector_id']}  {row['message'][:140]}")

    workdir = tempfile.mkdtemp(prefix="phase4-mutants-")
    try:
        mutants = mutant_stage(workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print()
    width = max(len(row["name"]) for row in mutants)
    for row in mutants:
        print(f"  {row['outcome']:<9} {row['name']:<{width}}  {row['must_fire']}")
        if row["outcome"] == "ERROR":
            print(f"            {row['error'][:200]}")

    contract = PA.load_json(os.path.join(PA.PHASE4_ROOT,
                                         "PHASE4_CONTRACT.json"), dict)
    declared = {d["detector_id"] for d in contract["detector_registry"]}
    owned = {row["must_fire"] for row in mutants}
    unexercised = sorted(declared - owned)
    undeclared = sorted(owned - declared)
    rejected = sum(1 for row in mutants if row["outcome"] == "REJECTED")

    print()
    print(f"mutants   : {rejected}/{len(mutants)} rejected")
    print(f"detectors : {len(owned & declared)}/{len(declared)} exercised")
    if unexercised:
        print(f"  NOT exercised: {unexercised}")
    if undeclared:
        print(f"  owned but NOT declared: {undeclared}")

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "PHASE4_SUITE_RESULTS.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"detectors_declared": sorted(declared),
                   "detectors_undeclared": undeclared,
                   "detectors_unexercised": unexercised, "green": green,
                   "mutants": mutants, "mutants_rejected": rejected,
                   "red": red}, handle, indent=2, sort_keys=True,
                  ensure_ascii=False)
        handle.write("\n")
    print(f"wrote {path}")

    ok = (red["outcome"] == "REFUSED"
          and green["verdict"] == "GREEN"
          and green["oracle_agrees"]
          and rejected == len(mutants)
          and not unexercised
          and not undeclared)
    print()
    print(f"SUITE : {'GREEN' if ok else 'RED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

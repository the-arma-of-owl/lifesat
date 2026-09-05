#!/usr/bin/env python3
"""validate_phase4.py — the Phase 4 repair and its successor package, judged.

    python3 validate_phase4.py \\
        --expect-phase4-settlement-sha256 <PIN> [--json OUT]

Order, and each step stops the validation rather than degrading:

  0. this root's own executables — tools AND candidate scorer — before anything
     else is read
  1. the Phase 4 settlement: mandatory, externally pinned, binding the
     historical contract and seal, both scorer digests, the raw trees and the
     rollback target
  2. the historical corrected package is byte-exact — the rollback target must
     survive the phase untouched, and the pre-repair scorer must still be the
     pinned one, proving the repair went into the candidate and not in place
  3. corpus identity: every one of the 1200 raw inputs is the byte the
     historical INPUT_MANIFEST recorded
  4. the join, over the WHOLE corpus: conservation, dispositions, ordinal
     health, the time witness, and agreement with the independent oracle
  5. invariance: what the repair moved, and what it was not allowed to move
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import p4_authority as PA          # noqa: E402
import p4_checks as PC             # noqa: E402
import p4_identity as PI           # noqa: E402
import p4_invariance as INV        # noqa: E402
import p4_rawtotals as RAW         # noqa: E402
import p4_reference_oracle as REF  # noqa: E402
import p4_settlement as PS         # noqa: E402

sys.path.insert(0, PA.CANDIDATE_SCORER)

import score as SCORE              # noqa: E402
from scoring import rndjoin        # noqa: E402


def scan_corpus(limit=None):
    """Bind and check every run. Returns (findings, totals)."""
    findings = []
    totals = {"alarm_rows": 0, "matched": 0, "observations": 0, "runs": 0,
              "time_inconsistent": 0, "unmatched": 0}
    dispositions = {name: 0 for name in rndjoin.DISPOSITIONS}
    runs = PA.corpus()["runs"]
    if limit:
        runs = runs[:limit]
    for run in runs:
        events_path, truth_path = PA.run_paths(run)
        scored = SCORE.score_run(events_path, truth_path)
        events = SCORE.load_events(events_path)
        binding = rndjoin.bind(events)
        conservation = binding.conservation
        identity = run["identity"]

        findings += PC.check_conservation(conservation, events, identity)
        findings += PC.check_dispositions(binding, identity)
        findings += PC.check_ordinal_health(conservation, identity)
        findings += PC.check_time_witness(conservation, identity)
        findings += PC.check_join_is_ordinal(events, binding.alarmed_ordinals,
                                             identity)
        findings += [dict(row, location=identity) for row in REF.compare(
            events, scored["effect_events"], scored["F3"]["RND"], binding)]

        declared = scored["F3"]["RND"].get("random_alarm_conservation")
        if declared != conservation:
            findings.append(PC.finding(
                "D-P4-CONSERVATION-01",
                "the conservation equation carried in the scored block is not "
                "the one the binding computed", identity))

        totals["runs"] += 1
        totals["alarm_rows"] += conservation["raw_alarm_rows"]
        totals["matched"] += conservation["matched"]
        totals["unmatched"] += conservation["unmatched"]
        totals["observations"] += conservation["observation_count"]
        totals["time_inconsistent"] += conservation["matched_time_inconsistent"]
        for name, count in conservation["by_disposition"].items():
            dispositions[name] += count
    totals["by_disposition"] = dispositions
    return findings, totals


def run(root, pin, limit=None):
    result = {"residual_findings": [], "verdict": "RED"}

    identity = PI.verify(root)
    if identity:
        result["residual_findings"] = identity
        result["executable_identity"] = "RED"
        return result
    result["executable_identity"] = "VERIFIED"

    try:
        settlement, settlement_sha = PS.load(root, pin)
    except PS.SettlementFinding as error:
        result["residual_findings"] = [PC.finding(error.detector, error.message,
                                                  error.location)]
        return result
    result["phase4_settlement_sha256"] = settlement_sha
    result["pre_repair_scorer_sha256"] = settlement["pre_repair_scorer_sha256"]
    result["repaired_scorer_sha256"] = settlement["repaired_scorer_sha256"]

    findings = list(PI.verify(
        root, settlement["wrapper_executable_inventory_sha256"]))
    findings += PC.check_field_registry("rndjoin")
    findings += INV.check_historical_untouched()

    corpus_findings, checked = INV.check_corpus_identity()
    findings += corpus_findings
    result["corpus_runs_verified"] = checked
    if settlement["expected_run_count"] != checked:
        findings.append(PC.finding(
            "D-P4-CORPUS-IDENTITY-01",
            f"the settlement expects {settlement['expected_run_count']} runs, "
            f"the manifest lists {checked}"))

    # Corpus totals, RECOUNTED from raw CSV and compared against every artefact
    # that states them. The recount path imports neither the scorer nor rndjoin.
    raw_totals = RAW.derived()
    findings += RAW.check_scope(raw_totals, "accepted corpus")
    findings += RAW.check_claims(root, raw_totals)
    result["raw_derived_totals"] = {key: value for key, value
                                    in sorted(raw_totals.items())
                                    if key != "identities"}
    result["canonical_claim"] = RAW.claim_line(raw_totals)

    contract = PA.load_json(os.path.join(root, "PHASE4_CONTRACT.json"), dict)
    stated = contract.get("corpus", {}).get("raw_derived_totals", {})
    if stated != result["raw_derived_totals"]:
        findings.append(PC.finding(
            "D-P4-RAW-TOTAL-01",
            f"the contract states corpus totals {stated}, the raw CSV recount "
            f"gives {result['raw_derived_totals']}", "PHASE4_CONTRACT.json"))

    scan_findings, totals = scan_corpus(limit)
    findings += scan_findings
    result["join_totals"] = totals

    # the scan and the independent recount must agree on the raw row count
    if limit is None and totals["alarm_rows"] != raw_totals["alarm_rows"]:
        findings.append(PC.finding(
            "D-P4-RAW-TOTAL-01",
            f"the join scan read {totals['alarm_rows']} raw alarm rows, the "
            f"independent CSV recount found {raw_totals['alarm_rows']}"))

    successor = os.path.join(root, settlement["successor_canonical_paths"][0])
    invariance = INV.compare(
        os.path.join(PA.HISTORICAL_PACKAGE, "CORRECTED_RESULTS.json"),
        successor, "CORRECTED_RESULTS.json")
    findings += invariance["findings"]
    result["invariance"] = {
        "arms_compared": invariance["arms_compared"],
        "invariant": invariance["invariant"],
        "legitimately_undefined_both_sides": [
            list(key) + [reason] for key, reason
            in invariance["legitimately_undefined_both_sides"]],
        "moved": [list(key) for key in invariance["moved"]],
    }
    result["successor_sha256"] = PA.sha256_file(successor)
    result["residual_findings"] = findings
    result["verdict"] = "PHASE4_CONFORMANT" if not findings else "RED"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=PA.PHASE4_ROOT)
    parser.add_argument("--expect-phase4-settlement-sha256", default=None)
    parser.add_argument("--limit", type=int, default=None,
                        help="scan only the first N runs (diagnostic only)")
    parser.add_argument("--json")
    args = parser.parse_args()
    result = run(args.root, args.expect_phase4_settlement_sha256, args.limit)

    print(f"executable identity        : "
          f"{result.get('executable_identity', 'RED')}")
    if result.get("phase4_settlement_sha256"):
        print(f"phase 4 settlement         : "
              f"{result['phase4_settlement_sha256']}  (external pin matched)")
        print(f"  pre-repair scorer         : "
              f"{result['pre_repair_scorer_sha256']}")
        print(f"  repaired scorer           : {result['repaired_scorer_sha256']}")
    if "corpus_runs_verified" in result:
        print(f"  corpus runs verified      : {result['corpus_runs_verified']}")
    if result.get("canonical_claim"):
        print(f"  raw CSV recount           : {result['canonical_claim']}")
    totals = result.get("join_totals")
    if totals:
        print()
        print(f"random alarm join over the corpus")
        print(f"  runs scanned              : {totals['runs']}")
        print(f"  raw alarm rows            : {totals['alarm_rows']}")
        print(f"  matched                   : {totals['matched']}")
        print(f"  unmatched                 : {totals['unmatched']}")
        print(f"  time-inconsistent matches : {totals['time_inconsistent']}")
        print(f"  conservation              : "
              f"{totals['alarm_rows']} == {totals['matched']} + "
              f"{totals['unmatched']}  "
              f"{totals['alarm_rows'] == totals['matched'] + totals['unmatched']}")
    inv = result.get("invariance")
    if inv:
        print()
        print(f"invariance")
        print(f"  estimand arms compared    : {inv['arms_compared']}")
        print(f"  invariant                 : {inv['invariant']}")
        print(f"  moved                     : {len(inv['moved'])}")
        print(f"  undefined both sides      : "
              f"{len(inv['legitimately_undefined_both_sides'])}")
    print()
    print(f"residual findings          : {len(result['residual_findings'])}")
    for row in result["residual_findings"][:15]:
        print(f"  RED {row['detector_id']}  {row.get('location')}  "
              f"{row['message'][:150]}")
    print()
    print(f"VERDICT : {result['verdict']}")
    if args.json:
        directory = os.path.dirname(os.path.abspath(args.json))
        os.makedirs(directory, exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True,
                      ensure_ascii=False)
            handle.write("\n")
    return 0 if result["verdict"] == "PHASE4_CONFORMANT" else 1


if __name__ == "__main__":
    raise SystemExit(main())

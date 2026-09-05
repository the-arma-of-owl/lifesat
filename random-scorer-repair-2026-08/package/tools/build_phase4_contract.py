#!/usr/bin/env python3
"""build_phase4_contract.py — the Phase 4 repair contract and its change manifest.

This contract adds no scientific rule. The scoring contract stays 1.4.3-candidate
and its seal stays the accepted one. What it declares is the REPAIR: the
producer/consumer field registry, the join key, the terminal dispositions, the
conservation equation, the closed detector registry, and — line by line — every
file the repair touched.
"""

from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import p4_authority as PA         # noqa: E402
import p4_identity as PI          # noqa: E402
import p4_invariance as INV       # noqa: E402
import p4_rawtotals as RAW        # noqa: E402
import p4_settlement as PS        # noqa: E402

sys.path.insert(0, PA.CANDIDATE_SCORER)
from scoring import rndjoin       # noqa: E402

VERSION = "v8-phase4-random-scorer-1.0.0-candidate"
SCHEMA = "lifesat-v8-phase4-repair-contract/v1"

# Files the repair touched, and what changed in each. The candidate tree is a
# copy of the v7 analysis tree; everything not listed here is byte-identical to
# it, and `changed_files_are_exactly` is checked rather than asserted.
CHANGES = [
    ("scoring/rndjoin.py", "NEW",
     "the producer/consumer field registry, the join key, the terminal "
     "dispositions and the conservation equation"),
    ("scoring/families.py", "MODIFIED",
     "direct_detection_rnd joins on the arrival ordinal instead of reading a "
     "field that does not exist; the block now carries its conservation "
     "equation. One import line added."),
    ("scoring/output.py", "MODIFIED",
     "scorer_digest split into scorer_digest_of_analysis so the candidate tree "
     "can be digested by the ACCEPTED recipe; behaviour preserved."),
    ("build_corrected_package_v1.py", "MODIFIED",
     "SIM addressed explicitly (the candidate lives outside the v7 tree), the "
     "scorer digest taken from the candidate analysis root, and the scorer pin "
     "moved to the repaired digest."),
    ("tests/reference_scorer.py", "MODIFIED",
     "_score_rnd rewritten to derive the pairing from the TIME WITNESS. It "
     "previously carried the identical tmSeq defect and was therefore not an "
     "independent oracle at all."),
]

DETECTORS = [
    ("D-P4-JOIN-KEY-01",
     "the scored alarm set is not the registered arrival-ordinal join, or the "
     "field registry misdescribes what the producer emits"),
    ("D-P4-CONSERVATION-01",
     "raw alarm rows are not conserved: total != matched + Σ unmatched, or the "
     "binding accounts for fewer rows than the raw log carries"),
    ("D-P4-DISPOSITION-01",
     "an alarm row carries no terminal disposition, or one outside the declared "
     "set"),
    ("D-P4-ORDINAL-RANGE-01",
     "an alarm names an observation ordinal the run does not have"),
    ("D-P4-ORDINAL-DUPLICATE-01",
     "an alarm repeats an observation ordinal already claimed in its run"),
    ("D-P4-TIME-WITNESS-01",
     "a matched alarm/observation pair does not share a simulation time"),
    ("D-P4-ORACLE-AGREEMENT-01",
     "the ordinal derivation and the independent time derivation disagree"),
    ("D-P4-ORACLE-AMBIGUOUS-01",
     "the time witness cannot resolve an alarm because more than one "
     "observation shares its instant"),
    ("D-P4-INVARIANCE-01",
     "an estimand that does not read the random detector changed, or a "
     "join-independent arm of the random estimand changed"),
    ("D-P4-REPAIR-EFFECT-01",
     "a join-fed arm with a defined value is byte-identical to the historical "
     "one, or nothing moved at all"),
    ("D-P4-ANCHOR-01",
     "the scored random alarm count does not reproduce the plan's raw audit "
     "anchors, or differs between a scenario's defence cells"),
    ("D-P4-CORPUS-IDENTITY-01",
     "a raw input is not the byte the historical INPUT_MANIFEST recorded"),
    ("D-P4-RAW-TOTAL-01",
     "a stated corpus raw random-alarm total does not equal the total "
     "recounted from the raw CSV, an artefact states no checkable total at "
     "all, or the recount was taken over a run set other than the historical "
     "INPUT_MANIFEST's"),
    ("D-P4-HISTORICAL-IMMUTABLE-01",
     "the historical corrected package, its seal, or the pre-repair scorer "
     "changed"),
    ("D-P4-SCORER-IDENTITY-01",
     "the settled repaired scorer is not the live candidate scorer, or equals "
     "the pre-repair digest"),
    ("D-P4-WRAPPER-EXECUTABLE-IDENTITY-01",
     "this root's runnable files — tools AND candidate scorer — are not the "
     "closed set the settlement binds"),
    ("D-P4-SETTLEMENT-PIN-01",
     "no external pin was supplied, or the settlement does not match it"),
    ("D-P4-SETTLEMENT-PRESENT-01", "the Phase 4 settlement is absent"),
    ("D-P4-SETTLEMENT-MALFORMED-01",
     "the settlement is unreadable, wrongly typed, or a binding is not a digest"),
    ("D-P4-SETTLEMENT-KEYS-01",
     "the settlement key set is not the closed set, or its schema is not the "
     "declared one"),
    ("D-P4-SETTLEMENT-BINDING-01",
     "a settled authority binding disagrees with the pinned authority"),
    ("D-P4-MEMBERSHIP-SINGLE-01",
     "the successor canonical set does not hold exactly one member"),
]


def change_manifest():
    """Every candidate file, against the v7 original, with nothing implicit."""
    rows, unexpected = [], []
    declared = {path for path, _kind, _why in CHANGES}
    for base, dirs, files in os.walk(PA.CANDIDATE_SCORER):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            full = os.path.join(base, name)
            relative = os.path.relpath(full, PA.CANDIDATE_SCORER)
            original = os.path.join(PA.V7_ANALYSIS, relative)
            live = PA.sha256_file(full)
            if not os.path.exists(original):
                state = "NEW"
                before = None
            else:
                before = PA.sha256_file(original)
                state = "UNCHANGED" if before == live else "MODIFIED"
            if state != "UNCHANGED" and relative not in declared:
                unexpected.append(relative)
            rows.append({"path": relative, "sha256_after": live,
                         "sha256_before": before, "state": state})
    removed = []
    for base, dirs, files in os.walk(PA.V7_ANALYSIS):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            relative = os.path.relpath(os.path.join(base, name), PA.V7_ANALYSIS)
            if not os.path.exists(os.path.join(PA.CANDIDATE_SCORER, relative)):
                removed.append(relative)
    return {
        "changed_files_are_exactly": sorted(declared),
        "declared_changes": [{"path": p, "state": k, "why": w}
                             for p, k, w in CHANGES],
        "files": rows,
        "removed": sorted(removed),
        "summary": {
            "modified": sum(1 for r in rows if r["state"] == "MODIFIED"),
            "new": sum(1 for r in rows if r["state"] == "NEW"),
            "removed": len(removed),
            "total": len(rows),
            "unchanged": sum(1 for r in rows if r["state"] == "UNCHANGED"),
        },
        "undeclared_changes": sorted(unexpected),
    }


def build():
    changes = change_manifest()
    return {
        "change_manifest": changes,
        "conservation_equation": {
            "dispositions": list(rndjoin.DISPOSITIONS),
            "rule": (
                "Every raw rnd.alarm row receives exactly ONE terminal "
                "disposition, and total == matched + Σ unmatched, anchored to "
                "the RAW LOG rather than to the binder's own bookkeeping. A "
                "binder that filters unmatched rows balances its own books "
                "perfectly, which is precisely how a silent drop hides."),
            "statement": "raw_alarm_rows == matched + unmatched",
        },
        "contract_version": VERSION,
        "corpus": {
            "canonical_claim": RAW.claim_line(RAW.derived()),
            "raw_derived_totals": {
                key: value for key, value in sorted(RAW.derived().items())
                if key != "identities"
            },
            "rule": (
                "The successor consumes EXACTLY the corpus the historical "
                "package consumed, read from its own INPUT_MANIFEST with "
                "per-run digests. Rebuilding the run list instead of reading it "
                "would make 'only the scorer changed' uncheckable."),
            "runs": PA.corpus()["manifest"]["selected_runs"],
            "totals_are_derived_not_stated": (
                "Every number above is recounted from the raw CSV of the "
                "manifest's runs by tools/p4_rawtotals.py, which imports "
                "neither the scorer nor rndjoin so it cannot inherit an "
                "assumption from the code it checks. The first Phase 4 round "
                "stated 9828 here: that came from a shell glob "
                "`*-s*-r0-events.csv`, which also matches the two illustrative "
                "A6s-safe runs and yields 1202 runs. The accepted corpus is "
                "1200 runs and 9812 alarms. The failure was SCOPE, not "
                "arithmetic, so D-P4-RAW-TOTAL-01 checks the run set as well "
                "as the tally."),
        },
        "defect": {
            "consumer_was": (
                'alarmed = {r["f"].get("tmSeq") for r in events '
                'if r["cat"] == "rnd.alarm"}'),
            "producer_emits": (
                'collector->logEvent("rnd.alarm", '
                '{{"n", std::to_string(observations)}})'),
            "source_ids": ["V7-N-103", "V7-N-118", "V7-N-120", "V7-N-127",
                           "V7-N-128", "V7-N-129", "V7-N-130", "V7-N-131",
                           "V7-N-132", "V7-N-133", "V7-N-134", "V7-N-135",
                           "V7-N-136", "V7-N-137"],
            "two_errors_not_one": (
                "1. WRONG FIELD NAME — `tmSeq` is not emitted; `n` is. "
                "2. WRONG UNIT — even spelled correctly, a telemetry SEQUENCE "
                "NUMBER is not an ARRIVAL ORDINAL. Recounted from the raw CSV "
                "of the accepted corpus, seq equals n for not one alarm."),
            "why_it_was_silent": (
                "`tmSeq` is absent from every alarm row, so the key set "
                "collapsed to {None} and no observation carrying a `seq` could "
                "ever match. The scorer reported zeros instead of raising: the "
                "random baseline looked like a detector that never fires."),
        },
        "detector_registry": [{"detector_id": d, "statement": s}
                              for d, s in DETECTORS],
        "invariance": {
            "join_dependent_arms": sorted(INV.JOIN_DEPENDENT_ARMS),
            "join_independent_arms": sorted(INV.JOIN_INDEPENDENT_ARMS),
            "plan_alarm_anchors": dict(INV.PLAN_ALARM_ANCHORS),
            "random_estimands": list(INV.RANDOM_ESTIMANDS),
            "rule": (
                "Every estimand that does not read the random detector must be "
                "byte-identical to the historical package. event_recall is "
                "computed by state.credit_alarms from alarm TIMES and never "
                "reads the join key, so it too must be identical — if it moved, "
                "the repair leaked. precision, fpr and recall are fed by the "
                "join and must move, unless they are undefined on BOTH sides "
                "for a declared reason."),
        },
        "join": dict(rndjoin.JOIN),
        "oracle_independence": {
            "production_derivation": "arrival ordinal — the field `n`",
            "reference_derivation": "time witness — the shared instant",
            "rule": (
                "The repository's existing analysis/tests/reference_scorer.py "
                "carried the IDENTICAL tmSeq defect, so agreement with it was "
                "worth nothing: an oracle that shares the assumption under test "
                "cannot falsify it. The Phase 4 oracle never reads `n` and "
                "never counts positions, and refuses an alarm whose instant is "
                "ambiguous rather than guessing."),
        },
        "producer_consumer_registry": {
            "consumer": dict(rndjoin.CONSUMER),
            "producer": dict(rndjoin.PRODUCER),
        },
        "schema": SCHEMA,
        "scientific_rules_unchanged": (
            "The scoring contract remains 1.4.3-candidate and its accepted seal "
            "is unchanged. No threshold, estimand definition, matching policy "
            "or window rule is altered. One join key is repaired."),
        "settlement_spec": {
            "closed_key_set": sorted(PS.CLOSED_KEY_SET),
            "external_pin_rule": (
                "--expect-phase4-settlement-sha256 pins the settlement from "
                "OUTSIDE this root. The validator refuses to run without it."),
            "schema": PS.SCHEMA,
        },
        "status": "CANDIDATE — pending independent Hermes audit; the historical "
                  "corrected package and seal remain the rollback target and "
                  "are byte-exact",
    }


def main():
    payload = build()
    path = os.path.join(PA.PHASE4_ROOT, "PHASE4_CONTRACT.json")
    digest = PA.write_json(path, payload)
    summary = payload["change_manifest"]["summary"]
    print(f"{payload['contract_version']}")
    print(f"  detectors                 {len(payload['detector_registry'])}")
    print(f"  corpus runs               {payload['corpus']['runs']}")
    print(f"  {payload['corpus']['canonical_claim']}")
    print(f"  candidate scorer files    {summary['total']} "
          f"({summary['new']} new, {summary['modified']} modified, "
          f"{summary['unchanged']} unchanged, {summary['removed']} removed)")
    undeclared = payload["change_manifest"]["undeclared_changes"]
    print(f"  undeclared changes        {undeclared if undeclared else 'none'}")
    print(f"PHASE4_CONTRACT.json        {digest}")
    return 1 if undeclared else 0


if __name__ == "__main__":
    raise SystemExit(main())

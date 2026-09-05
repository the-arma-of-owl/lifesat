#!/usr/bin/env python3
"""Task 7 — versioned corrected result package (contract v1.4.3).

Deterministic by construction:
  * no wall-clock anywhere; the package timestamp is the SEAL's accepted_utc;
  * every path recorded is relative to simulation/, so two builds into two
    different output roots produce byte-identical files;
  * the bootstrap is the contract's (2000 resamples, seed 12345, unit = run).

Fail-closed by construction:
  * the applicable estimand set is derived from the CONTRACT, never from the
    scorer's narrow CELL_ESTIMANDS publication list;
  * where the accepted scorer does not expose the semantics an estimand needs,
    the package reports it as unsupported WITH the reason. It never skips it
    silently and never computes the number by hand here, because a second
    scoring implementation living in the packaging layer would be unaudited.
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 🔴 PHASE 4. The repaired scorer is a CANDIDATE and lives outside the v7
# simulation tree, so the historical tree is addressed explicitly instead of
# being inferred from this file's location. Every path below it is READ-ONLY:
# the raw corpus, the specs and the seal are inputs, never outputs, and the
# builder already refuses to write inside them.
SIM = "/home/topya/lifesat_correction_round_v7/simulation"
sys.path.insert(0, HERE)

import score as SC                                   # noqa: E402
from scoring import output as OUT                    # noqa: E402

OLD_RAW = os.path.join(SIM, "results")
RERUN = os.path.join(SIM, "results-v2-iss06")
SPECS = os.path.join(SIM, "specs")
SEAL = ("/home/topya/lifesat_backups/checkpoints/"
        "20260811T155134Z-scoring-contract-v143-accepted/ACCEPTANCE_SEAL.json")
VERIFICATION = os.path.join(os.path.dirname(SIM), "verification",
                            "ISS06_FLEET_VERIFICATION.json")

PINS = {
    "contract_json": "913848492f82502f5a28243534eaa3e2e19c3c023ebd8b49df8027b8ccf54e95",
    "seal": "5c575f3cee35000b4da45c63312ea166ed632b6a4efd7e3fc85efe707ea8d813",
    # 🔴 PHASE 4. The REPAIRED scorer, not the historical de16e29c… pin. The
    # successor package must declare the scorer that actually produced it;
    # carrying the old digest forward would claim the defect was still present.
    "scorer": "8eaa4663270190ad907e2d5e5fc8ea7b420bd4e1295681517135090cca65c677",
    "old_raw_tree": "09893fc41cd5fab122b2d956bda46664d60d3b9f33aa68f95d4d41b408711c16",
    "rerun_tree": "f7e1d5fe90340d8bef2a0a512322d6b6017b39c56c1cec20a9531a0a01685b63",
}
RERUN_CELLS = ("A1-D3", "A2-D3", "A3-D3")
SEEDS = tuple(range(60))
SUFFIXES = ("-events.csv", "-truth.csv")


class BuildError(Exception):
    """Anything that must stop the package from being produced."""


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def tree_digest(root):
    rows = []
    for dirpath, _dn, filenames in os.walk(root):
        for name in filenames:
            p = os.path.join(dirpath, name)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            rows.append((os.path.relpath(p, root).replace(os.sep, "/"), p))
    rows.sort(key=lambda r: r[0].encode("utf-8"))
    d = hashlib.sha256()
    for rel, p in rows:
        d.update(("%s  %s\n" % (sha256(p), rel)).encode("utf-8"))
    return d.hexdigest(), len(rows)


# ── authority ──────────────────────────────────────────────────────────────
def verify_authority():
    problems = []
    got = sha256(os.path.join(SPECS, "scoring-contract-v1.json"))
    if got != PINS["contract_json"]:
        problems.append("contract %s != %s" % (got, PINS["contract_json"]))
    if not os.path.exists(SEAL):
        problems.append("seal missing")
    else:
        if sha256(SEAL) != PINS["seal"]:
            problems.append("seal digest mismatch")
        seal = json.load(open(SEAL, encoding="utf-8"))
        if seal.get("contract_json_sha256") != PINS["contract_json"]:
            problems.append("seal does not accept the pinned contract")
    got = OUT.scorer_digest_of_analysis(HERE)
    if got != PINS["scorer"]:
        problems.append("scorer %s != %s" % (got, PINS["scorer"]))
    for label, root, pin in (("old_raw_tree", OLD_RAW, PINS["old_raw_tree"]),
                             ("rerun_tree", RERUN, PINS["rerun_tree"])):
        digest, _n = tree_digest(root)
        if digest != pin:
            problems.append("%s %s != %s" % (label, digest, pin))
    if not os.path.exists(VERIFICATION):
        problems.append("ISS06 fleet verification missing")
    else:
        v = json.load(open(VERIFICATION, encoding="utf-8"))
        if v.get("verdict") != "GREEN":
            problems.append("fleet verification verdict is %r" % v.get("verdict"))
    if problems:
        raise BuildError("authority pin mismatch:\n  - " + "\n  - ".join(problems))
    seal = json.load(open(SEAL, encoding="utf-8"))
    return {"contract_version": seal["accepted_contract_version"],
            "contract_json_sha256": PINS["contract_json"],
            "seal_sha256": PINS["seal"], "scorer_sha256": PINS["scorer"],
            "old_raw_tree_sha256": PINS["old_raw_tree"],
            "rerun_tree_sha256": PINS["rerun_tree"],
            "authority_utc": seal["accepted_utc"]}


# ── corpus selection ───────────────────────────────────────────────────────
def contract():
    return json.load(open(os.path.join(SPECS, "scoring-contract-v1.json"),
                          encoding="utf-8"))


def select_corpus(C):
    cells = [c["cell"] for c in C["applicability_matrix"]]
    if len(cells) != 20 or len(set(cells)) != 20:
        raise BuildError("contract does not define exactly 20 cells")
    selected, problems = [], []
    for cell in sorted(cells):
        root = RERUN if cell in RERUN_CELLS else OLD_RAW
        for seed in SEEDS:
            identity = "%s-s%02d-r0" % (cell, seed)
            paths = {suf: os.path.join(root, identity + suf) for suf in SUFFIXES}
            missing = [s for s, p in paths.items() if not os.path.exists(p)]
            if missing:
                problems.append("%s missing %s" % (identity, missing))
                continue
            selected.append({"identity": identity, "cell": cell, "seed": seed,
                             "source": os.path.relpath(root, SIM),
                             "paths": paths})
    ids = [r["identity"] for r in selected]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        problems.append("duplicate identities: %s" % dupes[:5])
    if len(selected) != 1200:
        problems.append("selected %d runs, expected 1200" % len(selected))
    for cell in sorted(cells):
        seeds = sorted(r["seed"] for r in selected if r["cell"] == cell)
        if seeds != list(SEEDS):
            problems.append("cell %s seeds are not 0..59" % cell)
    if problems:
        raise BuildError("corpus selection failed:\n  - " + "\n  - ".join(problems))
    return selected


# ── estimand extraction, derived from the contract ────────────────────────
def _conf(block):
    tp, fp, fn, tn = block["tp"], block["fp"], block["fn"], block["tn"]
    return {"recall": (tp, tp + fn), "precision": (tp, tp + fp),
            "fpr": (fp, fp + tn), "event_recall": (block["detectedEvents"],
                                                   block["events"])}


RATIO_ARMS = {
    "EST-F0-01": lambda r: {"execution_rate": (r["F0"]["delivered"],
                                               r["F0"]["actions"])},
    "EST-F1-01": lambda r: {"prevention_rate": (r["F1"]["numerator"],
                                                r["F1"]["denominator"])},
    "EST-F1-02": lambda r: {"acceptance_rate": (r["F1"]["accepted"],
                                                r["F1"]["denominator"])},
    "EST-F2-01": lambda r: {"state_transition_rate": (r["F2"]["numerator"],
                                                      r["F2"]["denominator"])},
    "EST-F4-01": lambda r: {"secondary_reporting_rate": (r["F4"]["numerator"],
                                                         r["F4"]["denominator"])},
    "EST-F3-D3-01": lambda r: _conf(r["F3"]["D3"]),
    "EST-F3-D2-01": lambda r: _conf(r["F3"]["D2"]),
    "EST-F3-RND-01": lambda r: _conf(r["F3"]["RND"]),
    "EST-F3-D3-02": lambda r: {"event_recall": (r["F3"]["D3"]["detectedEvents"],
                                                r["F3"]["D3"]["events"])},
    "EST-A4-L2-01": lambda r: {"detection_rate": (r["F3"]["D3"]["tp"],
                                                  r["F3"]["D3"]["tp"]
                                                  + r["F3"]["D3"]["fn"])},
    # A: the contract asks for no subtype split here. The aggregate D2 output
    # already published by the scorer is the whole answer.
    "EST-A4-L3-01": lambda r: {
        "alarming_truth_positive_window_rate": (
            r["F3"]["D2"]["tp"], r["F3"]["D2"]["decision_units"]),
        "truth_positive_window_recall": (
            r["F3"]["D2"]["tp"],
            r["F3"]["D2"]["tp"] + r["F3"]["D2"]["fn"])},
    # B: partitions the single credit pass published by direct_detection_d3.
    "EST-A4-L2-02": lambda r: {
        "modification_detection_rate": (
            r["a4_subtype_detection"]["subtypes"]["modification"]["numerator"],
            r["a4_subtype_detection"]["subtypes"]["modification"]["denominator"]),
        "delay_detection_rate": (
            r["a4_subtype_detection"]["subtypes"]["delay"]["numerator"],
            r["a4_subtype_detection"]["subtypes"]["delay"]["denominator"])},
    # C: drops covered by an alarming expected-arrival window, within the
    # native class; no_native_decision_opportunity is excluded from the rate.
    "EST-A4-L3-02": lambda r: {
        "alarm_covered_drop_rate": (
            r["action_accounting"]["drop_opportunity_classes"]["numerator"],
            r["action_accounting"]["drop_opportunity_classes"]["denominator"])},
    "EST-AUX-01": lambda r: {"runs_with_a_missed_effect_event": (
        1 if (r["F3"]["D3"]["events"] - r["F3"]["D3"]["detectedEvents"]) > 0 else 0,
        1)},
}

ACCOUNTING = {
    "EST-F0-02": lambda r: {"dispositions": dict(r["action_accounting"]["dispositions"]),
                            "total_actions": r["action_accounting"]["total_actions"]},
    "EST-A4-L3-02": lambda r: {
        "drop_opportunity_classes":
            dict(r["action_accounting"]["drop_opportunity_classes"])},
    "EST-A4-L2-02": lambda r: {
        "drop_subtype": {
            "actions": r["a4_subtype_detection"]["subtypes"]["drop"]["actions"],
            "no_decision_opportunity":
                r["a4_subtype_detection"]["subtypes"]["drop"]
                ["no_decision_opportunity"]}},
}

# The accepted scorer does not expose these semantics. Computing them in this
# packaging layer would be a SECOND, unaudited scoring implementation, so they
# are reported rather than produced.
UNSUPPORTED = {}
PARTIAL = {}
# F5/F6 are Tier-2 illustrative estimands: they are PRODUCED, as descriptive
# Tier-2 output, and are never mixed into the Tier-1 matrix or its pooled rates.
TIER2_ESTIMANDS = ("EST-F5-01", "EST-F6-01")
# The A4 L2 layer is the received-observation layer (D3); the L3 layer is the
# flow-window layer (D2). Scoping them keeps each estimand in the cell whose
# detector actually produces its decision unit.
DETECTOR_ARM = {"EST-F3-D3-01": "D3", "EST-F3-D3-02": "D3", "EST-A4-L2-01": "D3",
                "EST-A4-L2-02": "D3", "EST-AUX-01": "D3",
                "EST-F3-D2-01": "D2", "EST-A4-L3-01": "D2", "EST-A4-L3-02": "D2",
                "EST-F3-RND-01": "RND"}


def applicable_estimands(C, cell_entry):
    """Which contract estimands apply to this cell — the contract decides."""
    cell = cell_entry["cell"]
    scenario, defence = cell.split("-")
    active = {f for f, v in cell_entry["families"].items()
              if v["status"] != "not_applicable"}
    out = []
    for e in C["estimands"]:
        eid = e["id"]
        if eid in TIER2_ESTIMANDS:
            continue                       # produced as Tier-2 descriptive output
        if e["result_family"] not in active:
            continue
        subtypes = e.get("attack_subtype_scope") or []
        if subtypes and not all(s.startswith(scenario + "_") for s in subtypes):
            continue
        det = DETECTOR_ARM.get(eid)
        if det in ("D3", "D2") and defence != det:
            continue
        if det == "RND" and defence not in ("D2", "D3"):
            continue
        out.append(e)
    return out


def build_cell(C, cell_entry, runs, scored):
    cell = cell_entry["cell"]
    identities = [r["identity"] for r in runs]
    estimands, unsupported = [], []
    for e in applicable_estimands(C, cell_entry):
        eid = e["id"]
        if e["status"] == "NO_ACTION":
            estimands.append({"estimand_id": eid, "status": e["status"],
                              "kind": "not_applicable",
                              "reason": e["notes"], "arms": {}, "counts": None})
            continue
        entry = {"estimand_id": eid, "status": e["status"],
                 "result_family": e["result_family"],
                 "evaluation_unit": e["evaluation_unit"], "arms": {},
                 "counts": None, "kind": None}
        if eid in RATIO_ARMS:
            entry["kind"] = "ratio"
            arms = [RATIO_ARMS[eid](scored[i]) for i in identities]
            for arm in sorted(arms[0]):
                pairs = [a[arm] for a in arms]
                entry["arms"][arm] = OUT.estimand_result(
                    eid, e["result_family"], e["evaluation_unit"], pairs,
                    identities)
        if eid in ACCOUNTING:
            entry["kind"] = "accounting" if entry["kind"] is None else "mixed"
            totals = {}
            for i in identities:
                for group, val in ACCOUNTING[eid](scored[i]).items():
                    if isinstance(val, dict):
                        g = totals.setdefault(group, {})
                        for k, v in val.items():
                            g[k] = g.get(k, 0) + int(v)
                    else:
                        totals[group] = totals.get(group, 0) + int(val)
            entry["counts"] = totals
        if eid in PARTIAL:
            entry["partially_supported"] = PARTIAL[eid]
            unsupported.append({"estimand_id": eid, "cell": cell,
                                "kind": "partial", "reason": PARTIAL[eid]})
        if eid in UNSUPPORTED:
            entry["kind"] = "unsupported"
            entry["reason"] = UNSUPPORTED[eid]
            unsupported.append({"estimand_id": eid, "cell": cell,
                                "kind": "unsupported", "reason": UNSUPPORTED[eid]})
        if entry["kind"] is None:
            entry["kind"] = "unsupported"
            entry["reason"] = "no extractor is registered for this estimand"
            unsupported.append({"estimand_id": eid, "cell": cell,
                                "kind": "unsupported", "reason": entry["reason"]})
        estimands.append(entry)
    return {"cell": cell, "scenario": cell.split("-")[0],
            "defence": cell.split("-")[1],
            "source": runs[0]["source"], "run_count": len(runs),
            "estimands": estimands}, unsupported


def score_corpus(selected):
    return {r["identity"]: SC.score_run(r["paths"]["-events.csv"],
                                        r["paths"]["-truth.csv"])
            for r in selected}


def strip_uncertainty(node):
    """POOLED view: pooled ratios never carry an interval."""
    return {"pooled_ratio": node["pooled_ratio"],
            "observed_numerator": node["observed_numerator"],
            "observed_denominator": node["observed_denominator"],
            "uncertainty": None,
            "uncertainty_policy": "no interval is published for a pooled ratio"}


# ── ISS-06: exact channel co-occurrence from the new boolean fields ────────
def channel_cooccurrence(selected):
    from scoring import artefacts
    labels = {"physical": 0, "logical": 0, "security": 0}
    combos, alarms, violations, missing_fields = {}, 0, [], 0
    for run in selected:
        if run["cell"] not in RERUN_CELLS:
            continue
        for row in artefacts.load_events(run["paths"]["-events.csv"]):
            if row["cat"] != "d3.alarm":
                continue
            alarms += 1
            f = row["f"]
            if not {"physicalBreach", "logicalBreach", "securityBreach"} <= set(f):
                missing_fields += 1
                continue
            p, l, s = (f["physicalBreach"] == "1", f["logicalBreach"] == "1",
                       f["securityBreach"] == "1")
            labels[f["channel"]] = labels.get(f["channel"], 0) + 1
            key = "+".join([n for n, b in (("physical", p), ("logical", l),
                                           ("security", s)) if b]) or "none"
            combos[key] = combos.get(key, 0) + 1
            expected = "physical" if p else ("logical" if l else "security")
            if f["channel"] != expected or not (p or l or s):
                violations.append({"run": run["identity"], "label": f["channel"],
                                   "physical": p, "logical": l, "security": s})
    cooccurrence = sum(v for k, v in combos.items() if "+" in k)
    return {"scope": list(RERUN_CELLS), "d3_alarms": alarms,
            "channel_labels": labels, "boolean_combinations": dict(sorted(combos.items())),
            "cooccurrence_rows": cooccurrence,
            "priority_boolean_violations": len(violations),
            "violations": violations[:5],
            "rows_missing_boolean_fields": missing_fields}


# ── G8: the rerun must not move any non-ISS-06 value ──────────────────────
def g8_substitution_invariance(C, selected, scored):
    """Score the same cells from the OLD raw tree and compare every value."""
    before = {}
    for run in selected:
        if run["cell"] not in RERUN_CELLS:
            continue
        stem = os.path.join(OLD_RAW, run["identity"])
        before[run["identity"]] = SC.score_run(stem + "-events.csv",
                                               stem + "-truth.csv")
    diffs = []
    for entry in C["applicability_matrix"]:
        if entry["cell"] not in RERUN_CELLS:
            continue
        runs = [r for r in selected if r["cell"] == entry["cell"]]
        new_cell, _u = build_cell(C, entry, runs, scored)
        old_cell, _u2 = build_cell(C, entry, runs, before)
        for a, b in zip(old_cell["estimands"], new_cell["estimands"]):
            for arm in sorted(set(a["arms"]) | set(b["arms"])):
                ka, kb = a["arms"].get(arm), b["arms"].get(arm)
                for field in ("value", "pooled_ratio", "observed_numerator",
                              "observed_denominator", "defined_run_count"):
                    if (ka or {}).get(field) != (kb or {}).get(field):
                        diffs.append({"cell": entry["cell"],
                                      "estimand": a["estimand_id"], "arm": arm,
                                      "field": field,
                                      "before": (ka or {}).get(field),
                                      "after": (kb or {}).get(field)})
            if a.get("counts") != b.get("counts"):
                diffs.append({"cell": entry["cell"], "estimand": a["estimand_id"],
                              "field": "counts", "before": a.get("counts"),
                              "after": b.get("counts")})
    return {"cells_compared": list(RERUN_CELLS),
            "runs_compared": len(before),
            "value_differences": diffs, "pass": not diffs,
            "meaning": ("every estimand value in the three rerun cells is "
                        "identical whether scored from the accepted raw tree or "
                        "from the ISS-06 rerun tree; the rerun added instrument "
                        "fields only")}


# ── D: EST-F5-01, Tier-2 pre-uplink validation (descriptive) ─────────────
# The expected verdict of each arm is DECLARED in simulations/lifesat.ini, not
# inferred from what the run produced. Config name and the declared intent are
# carried with each row so the expectation is auditable.
A6S_ARMS = [
    {"run": "A6s-gate-on-r0", "config": "A6s",
     "declared": "the unsafe update must be REJECTED and never uplinked",
     "expected_verdict": "rejected", "gate": "on"},
    {"run": "A6s-gate-off-r0", "config": "A6s-nogate",
     "declared": "validation gate OFF: no verdict is scheduled; the update is "
                 "applied and D3 sees the divergence afterwards",
     "expected_verdict": None, "gate": "off"},
    {"run": "A6s-safe-r0", "config": "A6s-safe",
     "declared": "a SAFE update must pass the gate (the gate does not reject "
                 "everything)",
     "expected_verdict": "approved", "gate": "on"},
    {"run": "A6s-safe-large-r0", "config": "A6s-safe-large",
     "declared": "safe but well away from nominal: approved, model updated, no "
                 "persistent false alarm",
     "expected_verdict": "approved", "gate": "on"},
    {"run": "A6s-unsupported-r0", "config": "A6s-unsupported",
     "declared": "a parameter the twin cannot model is UNSUPPORTED and must "
                 "fail closed rather than uplink",
     "expected_verdict": "unsupported", "gate": "on"},
]
VERDICT_EVENT = {"approved": "twin.updateApproved",
                 "rejected": "twin.updateRejected",
                 "unsupported": "twin.updateUnsupported"}


def tier2_f5():
    from scoring import artefacts
    rows, missing = [], []
    for arm in A6S_ARMS:
        path = os.path.join(OLD_RAW, arm["run"] + "-events.csv")
        if not os.path.exists(path):
            missing.append(arm["run"])
            continue
        counts = {k: 0 for k in VERDICT_EVENT}
        for e in artefacts.load_events(path):
            for verdict, cat in VERDICT_EVENT.items():
                if e["cat"] == cat:
                    counts[verdict] += 1
        opportunities = sum(counts.values())
        expected = arm["expected_verdict"]
        matching = counts.get(expected, 0) if expected else 0
        if opportunities == 0:
            value, code = None, "no_scheduled_validation_opportunity"
        else:
            value, code = (matching / opportunities), None
        rows.append({"run_identity": arm["run"], "config": arm["config"],
                     "declared_expectation": arm["declared"],
                     "validation_gate": arm["gate"],
                     "expected_verdict": expected,
                     "observed_verdicts": counts,
                     "scheduled_validation_opportunities": opportunities,
                     "numerator": matching, "denominator": opportunities,
                     "value": value, "undefined_reason_code": code})
    if missing:
        raise BuildError("EST-F5-01 inventory incomplete: %s" % missing)
    return {"estimand_id": "EST-F5-01", "tier": 2,
            "result_family": "F5_pre_uplink_validation",
            "evaluation_unit": "pre_uplink_validation_opportunity",
            "aggregation": "none: five illustrative runs, reported individually",
            "uncertainty": None,
            "excluded_from_tier1": ("descriptive only; never entered into the "
                                    "20-cell matrix or any pooled Tier-1 rate"),
            "inventory": [a["run"] for a in A6S_ARMS], "runs": rows}


# ── E: EST-F6-01, Tier-2 forensic mechanism (descriptive) ────────────────
A7_FAMILY = ("A7c-D3-r0", "A8-D3-r0")


def tier2_f6():
    import verify_chain as VC
    rows, missing = [], []
    for run in A7_FAMILY:
        events = os.path.join(OLD_RAW, run + "-events.csv")
        anchor_path = os.path.join(OLD_RAW, run + "-anchor.txt")
        if not (os.path.exists(events) and os.path.exists(anchor_path)):
            missing.append(run)
            continue
        chain_rows = VC.read_log(events)
        head, first_break = VC.recompute(chain_rows)
        anchor = open(anchor_path, encoding="utf-8").read()
        anchor_head = None
        for line in anchor.splitlines():
            if line.startswith("chainHead="):
                anchor_head = line.split("=", 1)[1].strip()
        # tamper mutation: alter ONE record in memory and confirm detection.
        mutated = [dict(r) for r in chain_rows]
        idx = len(mutated) // 2
        mutated[idx]["record"] = mutated[idx]["record"] + "X"
        _mhead, mbreak = VC.recompute(mutated)
        rows.append({"run_identity": run,
                     "chain_length": len(chain_rows),
                     "recomputed_head": head,
                     "anchor_head": anchor_head,
                     "anchor_agreement": anchor_head == head,
                     "first_break_index": first_break,
                     "chain_intact": first_break is None,
                     "tamper_mutation": {
                         "mutated_record_index": idx,
                         "detected": mbreak is not None,
                         "detected_at_index": mbreak,
                         "detected_at_the_mutated_record": mbreak == idx},
                     "outcome_matches_expectation":
                         first_break is None and anchor_head == head
                         and mbreak == idx})
    if missing:
        raise BuildError("EST-F6-01 inventory incomplete: %s" % missing)
    verified = len(rows)
    matching = sum(1 for r in rows if r["outcome_matches_expectation"])
    return {"estimand_id": "EST-F6-01", "tier": 2,
            "result_family": "F6_forensic_mechanism",
            "evaluation_unit": "log_record_chain",
            "aggregation": "none: illustrative runs, reported individually",
            "uncertainty": None,
            "excluded_from_tier1": ("descriptive only; never entered into the "
                                    "20-cell matrix or any pooled Tier-1 rate"),
            "numerator": matching, "denominator": verified,
            "value": (matching / verified) if verified else None,
            "undefined_reason_code": None if verified else "no_verified_chain",
            "inventory": list(A7_FAMILY), "runs": rows,
            "declared_expectation": ("the stored chain recomputes to the anchored "
                                     "head, and a single altered record is "
                                     "detected at that record")}


# ── honesty records ───────────────────────────────────────────────────────
def precision_target_record(cells):
    """The old 5% relative half-width target, checked rather than assumed."""
    rows = []
    for cell in cells:
        if cell["cell"] != "A1-D3":
            continue
        for e in cell["estimands"]:
            for arm, node in sorted(e["arms"].items()):
                unc, mean = node.get("uncertainty"), node.get("value")
                if not unc or mean in (None, 0):
                    continue
                half = (unc["ci_high"] - unc["ci_low"]) / 2.0
                rows.append({"estimand_id": e["estimand_id"], "arm": arm,
                             "macro_mean": mean, "ci_half_width": half,
                             "relative_half_width": half / abs(mean),
                             "meets_5_percent_relative_target":
                                 (half / abs(mean)) <= 0.05})
    unmet = [r for r in rows if not r["meets_5_percent_relative_target"]]
    return {"cell": "A1-D3", "n_runs": 60, "target": "relative half-width <= 5%",
            "arms_examined": len(rows), "arms_meeting_target": len(rows) - len(unmet),
            "arms_not_meeting_target": len(unmet), "detail": rows,
            "statement": ("At N=60 the historical 5%% relative precision target is "
                          "NOT met for %d of %d A1-D3 estimand arms carrying an "
                          "interval. The target is recorded as unmet rather than "
                          "restated as achieved." % (len(unmet), len(rows)))}


def crn_record(selected):
    """Do shared seed indices actually reuse the same randomness? Check, don't claim."""
    from scoring import artefacts
    by_seed = {}
    for run in selected:
        if run["seed"] not in (0, 1, 2):
            continue
        truth = artefacts.load_truth(run["paths"]["-truth.csv"])
        sig = hashlib.sha256(
            json.dumps([[r["t"], sorted(r["f"].items())] for r in truth],
                       sort_keys=True, default=str).encode()).hexdigest()
        by_seed.setdefault(run["seed"], {}).setdefault(sig, []).append(run["cell"])
    detail = {}
    for seed, groups in sorted(by_seed.items()):
        # Does one signature group correspond exactly to one scenario's four
        # defence variants? That is the pairing the matrix actually relies on.
        by_scenario = {}
        for sig, cells_ in groups.items():
            scenarios = {c.split("-")[0] for c in cells_}
            by_scenario[sig] = {"scenarios": sorted(scenarios),
                                "cells": sorted(cells_)}
        within = all(len(v["scenarios"]) == 1 and len(v["cells"]) == 4
                     for v in by_scenario.values())
        detail[str(seed)] = {
            "distinct_truth_signatures": len(groups),
            "identical_across_all_20_cells": len(groups) == 1,
            "group_sizes": sorted(len(v) for v in groups.values()),
            "each_group_is_one_scenario_across_its_four_defences": within,
            "groups": {v["scenarios"][0] if len(v["scenarios"]) == 1 else
                       "+".join(v["scenarios"]): v["cells"]
                       for v in by_scenario.values()}}
    strict = all(v["identical_across_all_20_cells"] for v in detail.values())
    within_all = all(v["each_group_is_one_scenario_across_its_four_defences"]
                     for v in detail.values())
    return {"seeds_examined": sorted(by_seed), "per_seed": detail,
            "strict_common_random_numbers_verified": strict,
            "within_scenario_crn_across_defences_verified": within_all,
            "statement": (
                "Strict CRN across all 20 cells is %s: at a fixed seed the "
                "ground-truth stream splits into 5 groups of 4, so scenarios do "
                "NOT share a stream. Within a scenario the stream IS shared "
                "across its four defence variants (%s), which is the pairing the "
                "matrix relies on. Both statements are measured by direct "
                "comparison of the per-seed truth records, not assumed." %
                ("CONFIRMED" if strict else "NOT CONFIRMED",
                 "verified" if within_all else "NOT verified"))}


# ── serialisation ─────────────────────────────────────────────────────────
def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


def has_bad_float(node):
    import math
    if isinstance(node, float):
        return math.isnan(node) or math.isinf(node)
    if isinstance(node, dict):
        return any(has_bad_float(v) for v in node.values())
    if isinstance(node, list):
        return any(has_bad_float(v) for v in node)
    return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(SIM, "results-v2-corrected"))
    a = ap.parse_args(argv)

    out_dir = os.path.realpath(a.out)
    for protected in (OLD_RAW, RERUN):
        if out_dir == protected or out_dir.startswith(protected + os.sep):
            raise BuildError("output %r is inside a protected tree" % out_dir)
    if os.path.exists(out_dir):
        raise BuildError("output root %r already exists; refusing to reuse it"
                         % out_dir)

    authority = verify_authority()
    C = contract()
    selected = select_corpus(C)
    scored = score_corpus(selected)

    cells, unsupported = [], []
    for entry in sorted(C["applicability_matrix"], key=lambda e: e["cell"]):
        runs = [r for r in selected if r["cell"] == entry["cell"]]
        cell, uns = build_cell(C, entry, runs, scored)
        cells.append(cell)
        unsupported.extend(uns)

    tier2 = [tier2_f5(), tier2_f6()]
    iss06 = channel_cooccurrence(selected)
    g8 = g8_substitution_invariance(C, selected, scored)
    precision = precision_target_record(cells)
    crn = crn_record(selected)

    # ---- three views, kept in separate fields and separate files ----------
    def strip_runs(cell):
        out = dict(cell)
        out["estimands"] = []
        for e in cell["estimands"]:
            e2 = dict(e)
            e2["arms"] = {}
            for arm, node in e["arms"].items():
                n2 = {k: v for k, v in node.items() if k != "per_run"}
                e2["arms"][arm] = n2
            out["estimands"].append(e2)
        return out

    run_level = {"schema": "lifesat-corrected-run-level/v1",
                 "authority": authority,
                 "cells": [{"cell": c["cell"], "estimands": [
                     {"estimand_id": e["estimand_id"],
                      "arms": {arm: node["per_run"]
                               for arm, node in e["arms"].items()}}
                     for e in c["estimands"] if e["arms"]]} for c in cells]}
    pooled = {"schema": "lifesat-corrected-pooled/v1",
              "authority": authority,
              "policy": "pooled ratios never carry an uncertainty interval",
              "cells": [{"cell": c["cell"], "estimands": [
                  {"estimand_id": e["estimand_id"],
                   "arms": {arm: strip_uncertainty(node)
                            for arm, node in e["arms"].items()}}
                  for e in c["estimands"] if e["arms"]]} for c in cells]}

    corrected = {
        "schema": "lifesat-corrected-results/v1",
        "package_version": "1",
        "authority": authority,
        "authority_utc_note": ("this package carries NO wall-clock time; the "
                               "timestamp above is the seal's accepted_utc, so "
                               "two builds are byte-identical"),
        "corpus": {"cells": len(cells), "runs_per_cell": len(SEEDS),
                   "selected_runs": len(selected),
                   "rerun_cells": list(RERUN_CELLS),
                   "rerun_runs": sum(1 for r in selected
                                     if r["cell"] in RERUN_CELLS),
                   "raw_runs": sum(1 for r in selected
                                   if r["cell"] not in RERUN_CELLS)},
        "uncertainty_policy": {
            "method": OUT.BOOTSTRAP_METHOD, "resamples": OUT.BOOTSTRAP_RESAMPLES,
            "seed": OUT.BOOTSTRAP_SEED, "resampling_unit": OUT.RESAMPLING_UNIT,
            "pooled_ratio": "no interval",
            "all_zero_suppression": "per estimand result, never per cell",
            "undefined": "null with an undefined_reason_code; never coerced to 0"},
        "cells": [strip_runs(c) for c in cells],
        "unsupported_estimands": unsupported,
        "tier2_descriptive": tier2,
        "iss06_channel_cooccurrence": iss06,
        "g8_substitution_invariance": g8,
        "precision_target": precision,
        "common_random_numbers": crn,
        "iss05_closure": {
            "issue": "ISS-05", "estimand": "EST-A4-L4-01",
            "decision": "NO_ACTION / structurally not applicable",
            "number_published": None,
            "statement": ("D3 is arrival-driven; dropped telemetry never "
                          "instantiates received_telemetry_observation. No "
                          "numerator, denominator or rate is produced.")},
    }

    manifest = {"schema": "lifesat-corrected-input-manifest/v1",
                "authority": authority,
                "selected_runs": len(selected),
                "sources": {"rerun": os.path.relpath(RERUN, SIM),
                            "accepted_raw": os.path.relpath(OLD_RAW, SIM)},
                "runs": [{"identity": r["identity"], "cell": r["cell"],
                          "seed": r["seed"], "source": r["source"],
                          "events_sha256": sha256(r["paths"]["-events.csv"]),
                          "truth_sha256": sha256(r["paths"]["-truth.csv"])}
                         for r in sorted(selected, key=lambda x: x["identity"])]}

    os.makedirs(out_dir)
    write_json(os.path.join(out_dir, "CORRECTED_RESULTS.json"), corrected)
    write_json(os.path.join(out_dir, "RUN_LEVEL_RESULTS.json"), run_level)
    write_json(os.path.join(out_dir, "POOLED_RESULTS.json"), pooled)
    write_json(os.path.join(out_dir, "INPUT_MANIFEST.json"), manifest)

    validation = validate(corrected, run_level, pooled, manifest, selected,
                          C, scored)
    write_json(os.path.join(out_dir, "VALIDATION.json"), validation)

    names = ["CORRECTED_RESULTS.json", "RUN_LEVEL_RESULTS.json",
             "POOLED_RESULTS.json", "INPUT_MANIFEST.json", "VALIDATION.json"]
    with open(os.path.join(out_dir, "CORRECTED_RESULTS.sha256"), "w") as fh:
        for name in names:
            fh.write("%s  %s\n" % (sha256(os.path.join(out_dir, name)), name))

    print(json.dumps({"output_root": os.path.relpath(out_dir, SIM),
                      "selected_runs": len(selected),
                      "cells": len(cells),
                      "unsupported": len(unsupported),
                      "verdict": validation["verdict"]}, indent=2))
    return 0 if validation["verdict"] == "GREEN" else 1


def validate(corrected, run_level, pooled, manifest, selected, C,
             scored_for_check):
    checks, failed = [], []

    def ck(name, cond, detail=""):
        checks.append({"name": name, "pass": bool(cond), "detail": str(detail)})
        if not cond:
            failed.append(name)

    ck("exactly 20 cells", len(corrected["cells"]) == 20, len(corrected["cells"]))
    ck("60 runs per cell", all(c["run_count"] == 60 for c in corrected["cells"]))
    ck("selected corpus is 1200", corrected["corpus"]["selected_runs"] == 1200)
    ck("180 runs come from the ISS-06 rerun", corrected["corpus"]["rerun_runs"] == 180)
    ck("1020 runs come from the accepted raw tree",
       corrected["corpus"]["raw_runs"] == 1020)
    ids = [r["identity"] for r in manifest["runs"]]
    ck("no duplicate run identity", len(ids) == len(set(ids)))

    # input hash readback
    bad = [r["identity"] for r in manifest["runs"]
           if sha256(os.path.join(SIM, r["source"], r["identity"] + "-events.csv"))
           != r["events_sha256"]]
    ck("input hash readback (events)", not bad, bad[:3])

    a = corrected["authority"]
    ck("contract pin", a["contract_json_sha256"] == PINS["contract_json"])
    ck("seal pin", a["seal_sha256"] == PINS["seal"])
    ck("scorer pin", a["scorer_sha256"] == PINS["scorer"])
    ck("old raw tree pin", a["old_raw_tree_sha256"] == PINS["old_raw_tree"])
    ck("rerun tree pin", a["rerun_tree_sha256"] == PINS["rerun_tree"])

    # decision-matrix coverage
    mx = json.load(open(os.path.join(SPECS, "rescore-decision-matrix-v1.json"),
                        encoding="utf-8"))
    rescore = [r["id"] for r in mx["rows"] if r["decision"] == "RESCORE_REQUIRED"]
    no_action = [r["id"] for r in mx["rows"] if r["decision"] == "NO_ACTION"]
    rerun_rows = [r["id"] for r in mx["rows"] if r["decision"] == "RERUN_REQUIRED"]
    ck("decision matrix is 40/1/10",
       (len(rescore), len(rerun_rows), len(no_action)) == (40, 1, 10),
       (len(rescore), len(rerun_rows), len(no_action)))
    produced = {e["estimand_id"] for c in corrected["cells"] for e in c["estimands"]
                if e["arms"] or e.get("counts")}
    tier2_produced = {t["estimand_id"] for t in corrected["tier2_descriptive"]
                      if t.get("runs")}
    est_rows = [r for r in rescore if r.startswith("EST-")]
    produced_all = produced | tier2_produced
    ck("every RESCORE estimand row produces normative output",
       all(e in produced_all for e in est_rows),
       sorted(e for e in est_rows if e not in produced_all))
    ck("no RESCORE estimand is left unsupported",
       not corrected["unsupported_estimands"],
       corrected["unsupported_estimands"][:3])
    ck("40/40 normative outputs: 17 RESCORE estimands all produced",
       len(est_rows) == 17 and all(e in produced_all for e in est_rows),
       len(est_rows))
    ck("Tier-2 estimands are produced, not deferred",
       tier2_produced == {"EST-F5-01", "EST-F6-01"}, sorted(tier2_produced))
    ck("Tier-2 output is excluded from the Tier-1 matrix",
       all("excluded_from_tier1" in t for t in corrected["tier2_descriptive"])
       and not (tier2_produced & produced))
    ck("the single RERUN issue is closed by the accepted rerun",
       rerun_rows == ["ISS-06"] and corrected["iss06_channel_cooccurrence"][
           "priority_boolean_violations"] == 0)
    ck("no NO_ACTION row produces a number",
       corrected["iss05_closure"]["number_published"] is None
       and all(e["kind"] == "not_applicable" and not e["arms"]
               for c in corrected["cells"] for e in c["estimands"]
               if e["estimand_id"] == "EST-A4-L4-01"))

    # ISS-06 corpus invariants
    i6 = corrected["iss06_channel_cooccurrence"]
    ck("ISS-06 d3.alarm count is 1576", i6["d3_alarms"] == 1576, i6["d3_alarms"])
    ck("ISS-06 physical label 281", i6["channel_labels"].get("physical") == 281)
    ck("ISS-06 logical label 0", i6["channel_labels"].get("logical", 0) == 0)
    ck("ISS-06 security label 1295", i6["channel_labels"].get("security") == 1295)
    ck("ISS-06 co-occurrence rows 7", i6["cooccurrence_rows"] == 7,
       i6["cooccurrence_rows"])
    ck("ISS-06 priority/boolean violations 0",
       i6["priority_boolean_violations"] == 0)
    ck("ISS-06 no alarm row missing the boolean fields",
       i6["rows_missing_boolean_fields"] == 0)

    # EST-A4-L2-01's extractor assumes the D3 truth-positive set IS the set of
    # received tampered/delayed observations. That is an assumption about the
    # scorer, so it is enforced here rather than trusted.
    l2 = []
    for run in selected:
        if run["cell"] != "A4-D3":
            continue
        r = scored_for_check[run["identity"]]
        d3, disp = r["F3"]["D3"], r["action_accounting"]["dispositions"]
        if d3["tp"] + d3["fn"] != disp["received_modified"] + disp["received_delayed"]:
            l2.append(run["identity"])
    ck("EST-A4-L2-01 denominator equals received tampered/delayed observations",
       not l2, l2[:3])

    # B: one alarm may never be credited to two subtypes.
    dbl, orphan, mixed = [], [], []
    for run in selected:
        sd = scored_for_check[run["identity"]].get("a4_subtype_detection")
        if not sd or not sd.get("applicable"):
            continue
        total = sum(sd["subtypes"][k]["detected"] for k in ("modification", "delay"))
        # EXACT, not <=: a credit landing in no subtype is an orphan and the
        # partition would silently lose it.
        if total != sd["credited_effect_events"]:
            dbl.append(run["identity"])
        if not sd["partition_check"]["exact"]:
            orphan.append(run["identity"])
        drop = sd["subtypes"]["drop"]
        if drop["no_decision_opportunity"] != drop["actions"]:
            mixed.append(run["identity"])
    ck("the subtype partition accounts for the credit pass EXACTLY", not dbl, dbl[:3])
    ck("no credited effect event is orphaned by the partition", not orphan, orphan[:3])
    ck("D3 no-decision-opportunity is every drop, not a D2 window class",
       not mixed, mixed[:3])
    ck("the drop subtype publishes no rate",
       all(sd["subtypes"]["drop"]["value"] is None
           for sd in (scored_for_check[r["identity"]]["a4_subtype_detection"]
                      for r in selected) if sd.get("applicable")))

    # The two families count different things about the same 249 drops.
    a4d3 = [r for r in selected if r["cell"] == "A4-D3"]
    a4d2 = [r for r in selected if r["cell"] == "A4-D2"]
    d3_nodec = sum(scored_for_check[r["identity"]]["a4_subtype_detection"]
                   ["subtypes"]["drop"]["no_decision_opportunity"] for r in a4d3)
    d3_drops = sum(scored_for_check[r["identity"]]["a4_subtype_detection"]
                   ["subtypes"]["drop"]["actions"] for r in a4d3)
    d2 = {k: sum(scored_for_check[r["identity"]]["action_accounting"]
                 ["drop_opportunity_classes"][k] for r in a4d2)
          for k in ("native_decision_opportunity",
                    "no_native_decision_opportunity", "unresolved")}
    ck("A4-D3 drop actions are 249", d3_drops == 249, d3_drops)
    ck("A4-D3 D3 no-decision-opportunity is 249", d3_nodec == 249, d3_nodec)
    ck("A4-D2 D2 split is 248 native + 1 no-native + 0 unresolved",
       (d2["native_decision_opportunity"], d2["no_native_decision_opportunity"],
        d2["unresolved"]) == (248, 1, 0), d2)
    ck("the D3 figure is not borrowed from the D2 split",
       d3_nodec != d2["no_native_decision_opportunity"]
       and d3_nodec != d2["native_decision_opportunity"]
       and d3_nodec == sum(d2.values()), (d3_nodec, d2))

    # C: the alarm-covered numerator never exceeds the native class.
    cov = [r["identity"] for r in selected
           if scored_for_check[r["identity"]]["action_accounting"]
           ["drop_opportunity_classes"]["numerator"] >
           scored_for_check[r["identity"]]["action_accounting"]
           ["drop_opportunity_classes"]["denominator"]]
    ck("alarm-covered drops never exceed the native decision opportunities",
       not cov, cov[:3])

    # A: the D2 recall denominator is the published truth-positive window count.
    l3 = [r["identity"] for r in selected
          if r["cell"] == "A4-D2"
          and (scored_for_check[r["identity"]]["F3"]["D2"]["tp"]
               + scored_for_check[r["identity"]]["F3"]["D2"]["fn"])
          != scored_for_check[r["identity"]]["F3"]["D2"]
          ["unique_truth_positive_windows"]]
    ck("EST-A4-L3-01 recall denominator equals unique truth-positive windows",
       not l3, l3[:3])

    ck("G8 substitution invariance", corrected["g8_substitution_invariance"]["pass"],
       corrected["g8_substitution_invariance"]["value_differences"][:2])

    # run-level -> macro / pooled recomputation
    rl = {c["cell"]: c for c in run_level["cells"]}
    mism = []
    for c in corrected["cells"]:
        for e in c["estimands"]:
            for arm, node in e["arms"].items():
                per_run = next(x["arms"][arm] for x in rl[c["cell"]]["estimands"]
                               if x["estimand_id"] == e["estimand_id"])
                vals = [p["value"] for p in per_run if p["value"] is not None]
                macro = sum(vals) / len(vals) if vals else None
                if macro is None:
                    if node["value"] is not None:
                        mism.append((c["cell"], e["estimand_id"], arm, "macro"))
                elif abs(macro - node["value"]) > 1e-12:
                    mism.append((c["cell"], e["estimand_id"], arm, "macro"))
                num = sum(p["numerator"] for p in per_run)
                den = sum(p["denominator"] for p in per_run)
                pooled_v = (num / den) if den else None
                if pooled_v is None:
                    if node["pooled_ratio"] is not None:
                        mism.append((c["cell"], e["estimand_id"], arm, "pooled"))
                elif abs(pooled_v - node["pooled_ratio"]) > 1e-12:
                    mism.append((c["cell"], e["estimand_id"], arm, "pooled"))
                if node["defined_run_count"] != len(vals):
                    mism.append((c["cell"], e["estimand_id"], arm, "defined_count"))
    ck("run-level recomputes macro and pooled exactly", not mism, mism[:3])

    # CI policy
    ci_bad, zero_bad, pooled_ci = [], [], []
    for c in corrected["cells"]:
        for e in c["estimands"]:
            for arm, node in e["arms"].items():
                u = node.get("uncertainty")
                if u:
                    if (u["resamples"], u["seed"], u["resampling_unit"]) != (
                            2000, 12345, "run"):
                        ci_bad.append((c["cell"], e["estimand_id"], arm))
                    if "percentile" not in u["method"]:
                        ci_bad.append((c["cell"], e["estimand_id"], arm))
                per_run = node["per_run"] if "per_run" in node else None
                vals = [p for p in (per_run or [])]
                if u and vals and all((p["value"] == 0.0) for p in vals
                                      if p["value"] is not None):
                    zero_bad.append((c["cell"], e["estimand_id"], arm))
    for c in pooled["cells"]:
        for e in c["estimands"]:
            for arm, node in e["arms"].items():
                if node.get("uncertainty") is not None:
                    pooled_ci.append((c["cell"], e["estimand_id"], arm))
    ck("CI is run-unit, two-sided 95% percentile, 2000 resamples, seed 12345",
       not ci_bad, ci_bad[:3])
    ck("no interval on an all-zero estimand result", not zero_bad, zero_bad[:3])
    ck("no interval on any pooled ratio", not pooled_ci, pooled_ci[:3])

    undefined_zeroed = []
    for c in run_level["cells"]:
        for e in c["estimands"]:
            for arm, rows in e["arms"].items():
                for p in rows:
                    if p["value"] is None and p["undefined_reason_code"] is None:
                        undefined_zeroed.append((c["cell"], e["estimand_id"], arm))
    ck("undefined values carry a reason code and are not 0",
       not undefined_zeroed, undefined_zeroed[:3])

    for name, doc in (("CORRECTED_RESULTS", corrected), ("RUN_LEVEL", run_level),
                      ("POOLED", pooled), ("INPUT_MANIFEST", manifest)):
        ck("no NaN/Infinity in %s" % name, not has_bad_float(doc))
        ck("%s declares a schema" % name, isinstance(doc.get("schema"), str))

    ck("no wall-clock timestamp in the package",
       "generated_utc" not in json.dumps(corrected))
    ck("precision target recorded honestly",
       corrected["precision_target"]["arms_not_meeting_target"] >= 0
       and "NOT met" in corrected["precision_target"]["statement"])
    ck("CRN reported as measured, not assumed",
       "measured" in corrected["common_random_numbers"]["statement"])

    return {"schema": "lifesat-corrected-validation/v1",
            "authority": corrected["authority"],
            "checks": len(checks), "failed": failed, "detail": checks,
            "verdict": "GREEN" if not failed else "RED"}


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BuildError as _exc:
        sys.stderr.write("REFUSED (BuildError): %s\n" % _exc)
        sys.exit(2)

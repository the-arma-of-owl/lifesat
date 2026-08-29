#!/usr/bin/env python3
"""runpilot.py -- execute the complete deterministic one-seed pilot.

One seed per declared inferential and robustness cell, derived from the
accepted contract, executed with the real OMNeT++ executable, parsed from the
producer's own hash-chained CSV, and decided by the ACCEPTED oracle.

Every estimator, cell, metric, bound and verdict below comes from the accepted
Phase 2 v7 tools, imported and executed unchanged.  Phase 3 supplies raw events
and truth rows; it does not get a second opinion about what they mean.

The pilot is expected to be statistically underpowered and says so in the
package: one seed cannot reach the predeclared 93 decisive runs per arm, so the
verdict is INSUFFICIENT_EVIDENCE by the contract's own first ordered rule.
Nothing here may be read as production evidence.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ACCEPTED_TOOLS = os.environ.get("LIFESAT_TOOLS", str(Path(__file__).resolve().parents[2] / "tools"))
if ACCEPTED_TOOLS not in sys.path:
    sys.path.insert(0, ACCEPTED_TOOLS)

import authority        # noqa: E402
import canonical        # noqa: E402
import episodes as EP   # noqa: E402
import inventory        # noqa: E402
import rawlog           # noqa: E402
import runcell          # noqa: E402

# the accepted builders, unchanged
import build_fixtures as BF          # noqa: E402
import causal_core as CC             # noqa: E402
import settlement as SETTLEMENT      # noqa: E402
from estimands import build_cells, recompute_verdict  # noqa: E402
from external_identity import fill_external_identities  # noqa: E402

PILOT_ROOT = os.environ.get("LIFESAT_PILOT_ROOT", "runs/pilot")
PACKAGE_RELATIVE = "package/PHASE3_PILOT_RESULT_PACKAGE.json"


def run_all_cells(cells, root, reuse=True):
    """Executes every declared cell and returns its parsed real output."""
    out = {}
    for index, cell in enumerate(cells, 1):
        kind = cell["kind"]
        directory = os.path.join(root, "runs", kind, cell["run_id"])
        events_csv = os.path.join(directory, f"{cell['run_id']}-r0-events.csv")
        if reuse and os.path.exists(events_csv):
            result = {
                "anchor": os.path.join(directory, f"{cell['run_id']}-r0-anchor.txt"),
                "argv": runcell.command(cell, directory, cell["run_id"])[0],
                "events": events_csv, "exit_code": 0, "label": cell["run_id"],
                "stdout_tail": "(reused)",
                "truth": os.path.join(directory, f"{cell['run_id']}-r0-truth.csv"),
            }
        else:
            result = runcell.run(cell, directory)
        events = rawlog.read_events(result["events"])
        head = rawlog.verify_chain(events)
        anchor = dict(
            line.split("=", 1) for line in
            open(result["anchor"], encoding="utf-8").read().split()
            if "=" in line)
        if anchor.get("chainHead") != head:
            raise SystemExit(f"{cell['run_id']}: the recomputed chain head does "
                             f"not match the run's own anchor")
        truth = rawlog.read_truth(result["truth"])
        out[cell["run_id"]] = {
            "canonical_events": canonical.canonical_events(events, cell["run_id"]),
            "canonical_truth": canonical.canonical_truth(truth, cell["run_id"]),
            "cell": cell,
            "chain_head": head,
            "chain_length": len(events),
            "result": result,
        }
        print(f"  [{index:>2}/{len(cells)}] {cell['run_id']:<40} "
              f"{len(events):>5} events  {len(truth)} truth rows")
    return out


def reconcile(cells, observed):
    """Expected identity set == observed identity set, exactly."""
    expected = {c["run_id"] for c in cells}
    got = set(observed)
    duplicates = [k for k, n in collections.Counter(
        r["cell"]["run_id"] for r in observed.values()).items() if n > 1]
    report = {
        "duplicate": sorted(duplicates),
        "expected_count": len(expected),
        "extra": sorted(got - expected),
        "missing": sorted(expected - got),
        "observed_count": len(got),
        "exact": got == expected and not duplicates,
    }
    return report


def build(root, reuse=True):
    contract, _schema, digests = authority.load()
    cells = inventory.full_inventory(contract)
    print(f"contract {contract['contract_version']} "
          f"sha256 {digests['contract_sha256']}")
    print(f"pilot inventory: {len(cells)} cells "
          f"({sum(1 for c in cells if c['kind'] == 'inferential')} inferential, "
          f"{sum(1 for c in cells if c['kind'] == 'robustness')} robustness)")

    observed = run_all_cells(cells, root, reuse=reuse)
    identity = reconcile(cells, observed)
    if not identity["exact"]:
        raise SystemExit(f"identity reconciliation failed: {identity}")
    print(f"identity reconciliation: {identity['observed_count']}/"
          f"{identity['expected_count']} exact, no missing, extra or duplicate")

    inferential = [c for c in cells if c["kind"] == "inferential"]
    robustness = [c for c in cells if c["kind"] == "robustness"]

    ep_records, raw_events, raw_truth = [], [], []
    for cell in inferential:
        row = observed[cell["run_id"]]
        record = EP.build_episode(contract, cell, row["canonical_events"],
                                  row["canonical_truth"])
        ep_records.append(record)
        raw_events.extend(row["canonical_events"])
        raw_truth.extend(row["canonical_truth"])

    rb_runs, rb_events, rb_truth = [], [], []
    for cell in robustness:
        row = observed[cell["run_id"]]
        record = EP.build_episode(contract, cell, row["canonical_events"],
                                  row["canonical_truth"])
        rb_runs.append({"arm_id": cell["arm_id"], "episode": record,
                        "run_id": cell["run_id"]})
        rb_events.extend(row["canonical_events"])
        rb_truth.extend(row["canonical_truth"])

    events_by_episode = BF.group_events(raw_events)
    rb_by_episode = BF.group_events(rb_events)

    authority_dir = os.path.join(root, "authority")
    paths = {
        "raw_event": os.path.join(authority_dir, "PILOT_raw_event_authority.json"),
        "raw_truth": os.path.join(authority_dir, "PILOT_raw_truth_authority.json"),
        "rb_event": os.path.join(authority_dir, "PILOT_robustness_event_authority.json"),
        "rb_truth": os.path.join(authority_dir, "PILOT_robustness_truth_authority.json"),
    }
    CC.make_parents(paths["raw_event"])
    CC.write_json(paths["raw_event"], raw_events)
    CC.write_json(paths["raw_truth"], raw_truth)
    CC.write_json(paths["rb_event"], rb_events)
    CC.write_json(paths["rb_truth"], rb_truth)

    records, summaries = BF.build_robustness_records(contract, rb_runs, rb_by_episode)
    cells_block = build_cells(contract, ep_records)
    scope, verdict, derivation = recompute_verdict(contract, ep_records, cells_block)

    keys = {(e["pair_id"], e["arm"], e["run_seed_index"]) for e in ep_records}
    defined = {(e["pair_id"], e["arm"], e["run_seed_index"])
               for e in ep_records if e["evaluable"]}

    package = {
        "aggregation": {
            "defined_run_count": len(defined),
            "estimand_name": "decisive coverage over defined runs",
            "principal_estimator": "run_macro_mean_over_defined_runs",
            "total_run_count": len(keys),
        },
        "cells": cells_block,
        "channel_contribution": BF.build_channels(contract, ep_records,
                                                  events_by_episode),
        "confusion_matrix": BF.build_confusion(contract, ep_records),
        "contract_version": contract["contract_version"],
        "decision_mode": contract["decision_mode"]["mode"],
        "episodes": ep_records,
        "latency": BF.build_latency(ep_records),
        "manifest_membership": {
            "manifest_path": "RESULT_MANIFEST.json",
            "self_path": PACKAGE_RELATIVE,
        },
        "metrics": BF.build_metrics(contract, ep_records),
        # precision_and_replication_policy.pilot_isolation: pilot seeds may
        # appear ONLY in a package whose role is 'pilot', and they contribute to
        # no numerator, denominator, interval or scope gate anywhere else.
        "package_role": "pilot",
        "provenance": {
            "code_tree_digest": "",
            "config_sha256": "",
            "contract_sha256": digests["contract_sha256"],
            "payload_digest": "",
            "raw_event_authority_sha256": CC.sha256_file(paths["raw_event"]),
            "raw_truth_authority_sha256": CC.sha256_file(paths["raw_truth"]),
            "robustness_event_authority_sha256": CC.sha256_file(paths["rb_event"]),
            "robustness_truth_authority_sha256": CC.sha256_file(paths["rb_truth"]),
            "schema_sha256": digests["schema_sha256"],
            "source_authority_sha256": "",
        },
        "residual_generalisation_gap": {
            "claim_ledger_id": "FM-A-19",
            "items": [
                "anomaly types outside SP-1..SP-6",
                "thermal, attitude and flown-EPS subsystems are not modelled",
                "no flown-hardware evidence",
                "single-satellite, single-ground-station scope",
                "several decision rules depend on a ground-side ledger that "
                "records both the source and the received copy of each observation",
            ],
            "status": "IMMUTABLE_RESIDUAL_DIVERGENCE",
        },
        "robustness_arms": summaries,
        "robustness_runs": records,
        "schema": "lifesat-v8-causal-result-package/v7",
        "supported_scope": scope,
        "uncertainty": {
            "families_used": ["UNC-EXACT-BINOMIAL-BOUND",
                              "UNC-PAIRED-BLOCK-BONFERRONI-EXACT",
                              "UNC-PAIRED-BLOCK-BOOTSTRAP"],
            "interpretation_statement": (
                "THIS IS A PILOT PACKAGE AND IS DELIBERATELY UNDERPOWERED. One "
                "seed per declared cell cannot reach the predeclared minimum of "
                "93 unique decisive runs per arm, so no symptom class is "
                "precision_adequate and the verdict is INSUFFICIENT_EVIDENCE by "
                "the first ordered rule of the verdict decision tree. Every "
                "interval below is reported for structural conformance only: it "
                "is computed by the accepted estimators over a denominator of "
                "one, and it is not an estimate of anything. Arm-scoped and "
                "attack-conditional cell bounds are exact binomial bounds "
                "because those cells hold at most one episode per (pair_id, "
                "run_seed_index) block, which the validator checks per cell "
                "rather than assumes. The pooled cross-arm cell reports ONE "
                "endpoint, the one-sided lower bound the contradiction rule "
                "reads, built from two arm-specific exact Clopper-Pearson bounds "
                "at alpha/2 combined by the union bound. No gate reads it, and "
                "no pilot value may be presented as production evidence or as "
                "support for any published claim."),
        },
        "verdict": verdict,
        "verdict_derivation": derivation,
    }

    fill_external_identities(package)
    package["provenance"]["payload_digest"] = CC.payload_digest(package)

    package_path = CC.make_parents(os.path.join(root, PACKAGE_RELATIVE))
    package_digest = CC.write_json(package_path, package)

    manifest_path = os.path.join(root, "RESULT_MANIFEST.json")
    manifest_digest = CC.write_json(manifest_path, {
        "files": [{"path": PACKAGE_RELATIVE, "result_file_sha256": package_digest}],
        "rule": (
            "The result package never contains the SHA-256 of its own file; "
            "that digest lives here, detached. This manifest covers the PHASE 3 "
            "PILOT membership set, which is a different set from the accepted "
            "Phase 2 v7 canonical set and does not claim to be it."),
        "schema": "lifesat-v8-causal-result-manifest/v7",
    })
    settlement_path = os.path.join(root, "MEMBERSHIP_SETTLEMENT.json")
    settlement_digest = CC.write_json(settlement_path, SETTLEMENT.build(
        digests["contract_sha256"], [PACKAGE_RELATIVE],
        "RESULT_MANIFEST.json", manifest_digest))

    summary = {
        "contract_sha256": digests["contract_sha256"],
        "episodes": len(ep_records),
        "identity_reconciliation": identity,
        "manifest_sha256": manifest_digest,
        "package_sha256": package_digest,
        "predictions": dict(collections.Counter(
            e["predicted_class"] for e in ep_records)),
        "robustness_runs": len(records),
        "settlement_sha256": settlement_digest,
        "supported_scope": scope["symptom_classes_supported"],
        "verdict": verdict,
        "verdict_rule": derivation["matched_rule_order"],
    }
    CC.write_json(os.path.join(root, "PILOT_RUN_SUMMARY.json"), summary)

    print()
    print(f"episodes           {len(ep_records)}")
    print(f"robustness runs    {len(records)}")
    print(f"predictions        {summary['predictions']}")
    print(f"supported scope    {scope['symptom_classes_supported']}")
    print(f"VERDICT            {verdict}  (rule {derivation['matched_rule_order']})")
    print(f"package  sha256    {package_digest}")
    print(f"manifest sha256    {manifest_digest}")
    print(f"settlement sha256  {settlement_digest}")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=PILOT_ROOT)
    parser.add_argument("--fresh", action="store_true",
                        help="re-execute every cell instead of reusing raw logs")
    args = parser.parse_args()
    build(args.root, reuse=not args.fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

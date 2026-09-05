#!/usr/bin/env python3
"""p4_settlement.py — the Phase 4 settlement, fail-closed and externally pinned.

Closed key set, single successor member, and it binds the whole chain the
successor package rests on:

    historical_contract_json_sha256   the accepted scoring contract, unchanged
    historical_seal_sha256            the accepted seal, unchanged
    pre_repair_scorer_sha256          what the historical package was scored by
    repaired_scorer_sha256            what the SUCCESSOR was scored by — and it
                                      must differ from the pre-repair digest, or
                                      no repair was applied
    old_raw_tree_sha256               the immutable raw corpus
    rerun_tree_sha256                 the accepted ISS-06 rerun corpus
    historical_package_digests        the rollback target, member by member
    wrapper_executable_inventory_sha256
    expected_run_count                1200
    successor_canonical_paths         a SINGLE member

Absent, unreadable, malformed, wrongly typed, wrongly bound or wrongly pinned,
the validation is RED and STOPS.
"""

from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import p4_authority as PA  # noqa: E402

SCHEMA = "lifesat-v8-phase4-settlement/v1"
SETTLEMENT_NAME = "PHASE4_SETTLEMENT.json"

CLOSED_KEY_SET = frozenset({
    "expected_manifest_sha256", "expected_run_count",
    "historical_contract_json_sha256", "historical_package_digests",
    "historical_seal_sha256", "manifest_path", "old_raw_tree_sha256",
    "phase4_contract_sha256", "pre_repair_scorer_sha256",
    "repaired_scorer_sha256", "rerun_tree_sha256", "rule", "schema",
    "successor_canonical_paths", "wrapper_executable_inventory_sha256",
})

DIGEST_BINDINGS = (
    "expected_manifest_sha256", "historical_contract_json_sha256",
    "historical_seal_sha256", "old_raw_tree_sha256", "phase4_contract_sha256",
    "pre_repair_scorer_sha256", "repaired_scorer_sha256", "rerun_tree_sha256",
    "wrapper_executable_inventory_sha256",
)


class SettlementFinding(Exception):
    def __init__(self, detector, message, location=None):
        super().__init__(message)
        self.detector = detector
        self.message = message
        self.location = location


def build(contract_sha, manifest_path, manifest_sha, inventory_sha,
          canonical, run_count=1200):
    historical = PA.historical()
    return {
        "expected_manifest_sha256": manifest_sha,
        "expected_run_count": run_count,
        "historical_contract_json_sha256": PA.EXPECT_CONTRACT_JSON_SHA256,
        "historical_package_digests": dict(historical["digests"]),
        "historical_seal_sha256": PA.EXPECT_SEAL_SHA256,
        "manifest_path": manifest_path,
        "old_raw_tree_sha256": PA.EXPECT_OLD_RAW_TREE_SHA256,
        "phase4_contract_sha256": contract_sha,
        "pre_repair_scorer_sha256": PA.EXPECT_PRE_REPAIR_SCORER_SHA256,
        "repaired_scorer_sha256": PA.candidate_scorer_sha256(),
        "rerun_tree_sha256": PA.EXPECT_RERUN_TREE_SHA256,
        "rule": (
            "The validator receives expected_manifest_sha256 from HERE and "
            "never from the manifest under test. MANDATORY: absent, "
            "unreadable, malformed, wrongly typed, wrongly bound or wrongly "
            "pinned, the validation is RED and stops. Pin this file from "
            "outside with --expect-phase4-settlement-sha256. The successor set "
            "is a SINGLE member and does not replace the historical corrected "
            "package, which stays byte-exact as the rollback target."),
        "schema": SCHEMA,
        "successor_canonical_paths": sorted(canonical),
        "wrapper_executable_inventory_sha256": inventory_sha,
    }


def load(root, expected_external_sha):
    path = os.path.join(root, SETTLEMENT_NAME)
    if expected_external_sha is None:
        raise SettlementFinding(
            "D-P4-SETTLEMENT-PIN-01",
            "no external pin was supplied; the Phase 4 settlement must be "
            "pinned from outside and this validator refuses to run without one",
            path)
    if not os.path.exists(path):
        raise SettlementFinding("D-P4-SETTLEMENT-PRESENT-01",
                                f"{SETTLEMENT_NAME} is absent", path)
    live = PA.sha256_file(path)
    if live != expected_external_sha:
        raise SettlementFinding(
            "D-P4-SETTLEMENT-PIN-01",
            f"{SETTLEMENT_NAME} is {live}, not the external pin "
            f"{expected_external_sha}", path)
    try:
        payload = PA.load_json(path)
    except Exception as error:                       # noqa: BLE001
        raise SettlementFinding("D-P4-SETTLEMENT-MALFORMED-01",
                                f"unreadable settlement: {error}", path) from error
    if not isinstance(payload, dict):
        raise SettlementFinding(
            "D-P4-SETTLEMENT-MALFORMED-01",
            f"settlement root is {type(payload).__name__}", path)
    if set(payload) != CLOSED_KEY_SET:
        raise SettlementFinding(
            "D-P4-SETTLEMENT-KEYS-01",
            f"settlement key set {sorted(set(payload))} is not the closed set "
            f"{sorted(CLOSED_KEY_SET)}", path)
    if payload["schema"] != SCHEMA:
        raise SettlementFinding("D-P4-SETTLEMENT-KEYS-01",
                                f"schema {payload['schema']!r} != {SCHEMA!r}", path)
    for key in DIGEST_BINDINGS:
        value = payload.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise SettlementFinding(
                "D-P4-SETTLEMENT-MALFORMED-01",
                f"{key} is not a 64-character digest: {value!r}", path)

    # authority the settlement must agree with, live
    for key, pin in (("historical_contract_json_sha256",
                      PA.EXPECT_CONTRACT_JSON_SHA256),
                     ("historical_seal_sha256", PA.EXPECT_SEAL_SHA256),
                     ("pre_repair_scorer_sha256",
                      PA.EXPECT_PRE_REPAIR_SCORER_SHA256),
                     ("old_raw_tree_sha256", PA.EXPECT_OLD_RAW_TREE_SHA256),
                     ("rerun_tree_sha256", PA.EXPECT_RERUN_TREE_SHA256)):
        if payload[key] != pin:
            raise SettlementFinding(
                "D-P4-SETTLEMENT-BINDING-01",
                f"the settlement binds {key} {payload[key]}, the pinned "
                f"authority is {pin}", path)

    live_scorer = PA.candidate_scorer_sha256()
    if payload["repaired_scorer_sha256"] != live_scorer:
        raise SettlementFinding(
            "D-P4-SCORER-IDENTITY-01",
            f"the settlement binds repaired scorer "
            f"{payload['repaired_scorer_sha256']}, the live candidate scorer is "
            f"{live_scorer}", path)
    if payload["repaired_scorer_sha256"] == payload["pre_repair_scorer_sha256"]:
        raise SettlementFinding(
            "D-P4-SCORER-IDENTITY-01",
            "the repaired scorer digest equals the pre-repair one; the "
            "successor was produced by the unrepaired scorer", path)

    paths = payload["successor_canonical_paths"]
    if not isinstance(paths, list) or len(paths) != 1 \
            or not all(isinstance(p, str) and p for p in paths):
        raise SettlementFinding(
            "D-P4-MEMBERSHIP-SINGLE-01",
            f"the successor canonical set must hold exactly one path, got "
            f"{paths!r}", path)
    return payload, live

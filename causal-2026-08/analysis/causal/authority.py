#!/usr/bin/env python3
"""authority.py -- the accepted Phase 2 v7 contract, read only, verified first.

Phase 3 treats `accepted_phase2_v7/` as an immutable implementation contract.
Nothing in this package may edit it, and nothing may read it without first
proving the bytes are the accepted bytes.  The external settlement pin is the
outermost control and is supplied here as a constant because it came from
outside this candidate; the accepting party holds the same value.

Import this module and call `load()`; every other module in the package goes
through it, so there is exactly one place where the authority is opened and
exactly one place where its identity is checked.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

sys.dont_write_bytecode = True

ACCEPTED_ROOT = os.environ.get("LIFESAT_ACCEPTED_ROOT", "runs/accepted")
# Supplied by the accepting party, from its own records, not from this tree.
EXPECT_SETTLEMENT_SHA256 = \
    "0295a88743a545b27c8d6268c95e67d6b35643758b96e0d79c2ec6b4990582da"

# Read out of the accepted tree once, recorded here so that a silent
# replacement of the contract is a failure rather than a different experiment.
EXPECT_CONTRACT_SHA256 = \
    "dd3b1081045a0568d97de6dad83219f65d80b813f97afc27dccf0d3894cb0054"
EXPECT_SCHEMA_SHA256 = \
    "73c70d43b6ec3f0ed9c41afde2be8eec006d255cecbbc7a9a86f7b5480ac14b8"


class AuthorityError(Exception):
    """The accepted authority did not match its pinned identity."""


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_pinned(relative, expected):
    path = os.path.join(ACCEPTED_ROOT, relative)
    actual = sha256_file(path)
    if actual != expected:
        raise AuthorityError(f"{relative}: sha256 {actual} != pinned {expected}")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle), actual


_CACHE = {}


def load():
    """Returns (contract, schema, digests).  Fails closed on any mismatch."""
    if "loaded" not in _CACHE:
        settlement_path = os.path.join(ACCEPTED_ROOT, "MEMBERSHIP_SETTLEMENT.json")
        settlement_sha = sha256_file(settlement_path)
        if settlement_sha != EXPECT_SETTLEMENT_SHA256:
            raise AuthorityError(
                f"MEMBERSHIP_SETTLEMENT.json: sha256 {settlement_sha} != external "
                f"pin {EXPECT_SETTLEMENT_SHA256}")
        contract, contract_sha = _read_pinned(
            "V8_CAUSAL_EXPERIMENT_CONTRACT.json", EXPECT_CONTRACT_SHA256)
        schema, schema_sha = _read_pinned(
            "V8_CAUSAL_RESULT_SCHEMA.json", EXPECT_SCHEMA_SHA256)
        # The settlement binds the contract digest; check that binding rather
        # than trusting two independent pins to agree by luck.
        with open(settlement_path, encoding="utf-8") as handle:
            settlement = json.load(handle)
        if settlement.get("contract_sha256") != contract_sha:
            raise AuthorityError(
                "settlement contract_sha256 does not bind the contract on disk")
        _CACHE["loaded"] = (contract, schema, {
            "contract_sha256": contract_sha,
            "schema_sha256": schema_sha,
            "settlement_sha256": settlement_sha,
        })
    return _CACHE["loaded"]


def contract():
    return load()[0]


def schema():
    return load()[1]


def digests():
    return load()[2]


if __name__ == "__main__":
    c, _s, d = load()
    print(f"contract   {c['contract_version']}")
    for key, value in sorted(d.items()):
        print(f"{key:<20} {value}")
    print("accepted authority INTACT against the external settlement pin")

#!/usr/bin/env python3
"""p4_checks.py — the guards over a random-alarm binding and a rescoring pass.

Each guard returns findings; none of them raises, and none of them repairs what
it finds. Detector ownership is one-to-one with the Phase 4 contract registry.
"""

from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def finding(detector, message, location=None):
    return {"detector_id": detector, "location": location, "message": message}


def check_conservation(conservation, events=None, location=None):
    """Every raw alarm row has exactly one terminal disposition.

    This is the plan's unmatched-row conservation equation. It is arithmetic on
    purpose: "no rows were dropped" is a claim, `total == matched + Σ unmatched`
    is a check that fails loudly when a binder starts filtering.

    ⚠️ The equation is anchored to the RAW LOG, not to the binding's own count.
    A binder that quietly filters unmatched rows balances its own books
    perfectly — that is exactly how a silent drop hides — so when `events` is
    supplied the raw rows are recounted here and compared.
    """
    findings = []
    total = conservation["raw_alarm_rows"]

    if events is not None:
        raw = sum(1 for row in events if row["cat"] == "rnd.alarm")
        if raw != total:
            findings.append(finding(
                "D-P4-CONSERVATION-01",
                f"the raw log carries {raw} rnd.alarm rows but the binding "
                f"accounts for {total}; {raw - total} rows were dropped before "
                f"they could be given a disposition", location))

    matched = conservation["matched"]
    unmatched = conservation["unmatched"]
    by_disposition = conservation["by_disposition"]

    if total != matched + unmatched:
        findings.append(finding(
            "D-P4-CONSERVATION-01",
            f"{total} raw alarm rows != {matched} matched + {unmatched} "
            f"unmatched; rows were dropped between the raw log and the score",
            location))
    if sum(by_disposition.values()) != total:
        findings.append(finding(
            "D-P4-CONSERVATION-01",
            f"the dispositions account for {sum(by_disposition.values())} rows "
            f"but {total} were read", location))
    if not conservation["exact"]:
        findings.append(finding(
            "D-P4-CONSERVATION-01",
            "the binding reports its own conservation equation as inexact",
            location))
    return findings


def check_dispositions(binding, location=None):
    """No row is left untyped, and every type is a declared one."""
    from scoring import rndjoin

    findings = []
    for index, row in enumerate(binding.rows, start=1):
        if row["disposition"] is None:
            findings.append(finding(
                "D-P4-DISPOSITION-01",
                f"alarm row {index} carries no terminal disposition", location))
        elif row["disposition"] not in rndjoin.DISPOSITIONS:
            findings.append(finding(
                "D-P4-DISPOSITION-01",
                f"alarm row {index} carries the undeclared disposition "
                f"{row['disposition']!r}", location))
    return findings


def check_ordinal_health(conservation, location=None):
    """Out-of-range and duplicate ordinals are reported, never absorbed.

    These are NOT expected from the accepted producer — `observations` is
    pre-incremented, so it is unique and in range by construction. That is
    precisely why a nonzero count matters: it means the artefact is not what the
    producer is supposed to emit.
    """
    findings = []
    counts = conservation["by_disposition"]
    if counts.get("unmatched_ordinal_out_of_range"):
        findings.append(finding(
            "D-P4-ORDINAL-RANGE-01",
            f"{counts['unmatched_ordinal_out_of_range']} alarms name an "
            f"observation ordinal outside [1, "
            f"{conservation['observation_count']}]", location))
    if counts.get("unmatched_duplicate_ordinal"):
        findings.append(finding(
            "D-P4-ORDINAL-DUPLICATE-01",
            f"{counts['unmatched_duplicate_ordinal']} alarms repeat an "
            f"observation ordinal already claimed in this run", location))
    return findings


def check_time_witness(conservation, location=None):
    """A matched pair must share the instant it was written in."""
    if conservation["matched_time_inconsistent"]:
        return [finding(
            "D-P4-TIME-WITNESS-01",
            f"{conservation['matched_time_inconsistent']} matched alarm/"
            f"observation pairs do not share a simulation time; the two rows "
            f"are written inside one handleTelemetry call, so a mismatch means "
            f"the ordinal does not address the row it claims to", location)]
    return []


def check_field_registry(location=None):
    """The registered producer/consumer fields are the ones actually emitted."""
    from scoring import rndjoin

    findings = []
    if rndjoin.JOIN["producer_key"] != "rnd.alarm field 'n'":
        findings.append(finding(
            "D-P4-JOIN-KEY-01",
            f"the registered producer key is {rndjoin.JOIN['producer_key']!r}, "
            f"not the emitted field 'n'", location))
    if "n" not in rndjoin.PRODUCER["fields"]:
        findings.append(finding(
            "D-P4-JOIN-KEY-01",
            "the producer registry does not declare the field 'n'", location))
    if "tmSeq" in rndjoin.PRODUCER["fields"]:
        findings.append(finding(
            "D-P4-JOIN-KEY-01",
            "the producer registry declares 'tmSeq', which no rnd.alarm row "
            "carries", location))
    seq = rndjoin.CONSUMER["fields"].get("seq", "")
    if "PROVENANCE ONLY" not in seq:
        findings.append(finding(
            "D-P4-JOIN-KEY-01",
            "the consumer registry does not mark 'seq' as provenance only; it "
            "is a spacecraft sequence number and is not a join key", location))
    return findings


def _legacy_alarmed(events):
    """What the OLD tmSeq/seq read credits — reproduced, not described."""
    keys = {row["f"].get("tmSeq") for row in events if row["cat"] == "rnd.alarm"}
    alarmed, position = set(), 0
    for row in events:
        if row["cat"] != "tm.recv":
            continue
        position += 1
        if row["f"].get("seq") in keys:
            alarmed.add(position)
    return alarmed


def check_join_is_ordinal(events, alarmed, location=None):
    """The scored alarm set must be exactly the registered ordinal join.

    The expected set is RECOMPUTED here from the raw rows rather than taken
    from the binding, so this guard is a check on the production join and not a
    restatement of it. It catches the original defect, an off-by-one reading of
    the ordinal, and any other substitution of the key.
    """
    findings = []
    observations = [row for row in events if row["cat"] == "tm.recv"]
    expected, seen = set(), set()
    for row in events:
        if row["cat"] != "rnd.alarm":
            continue
        try:
            ordinal = int(row["f"].get("n"))
        except (TypeError, ValueError):
            continue
        if 1 <= ordinal <= len(observations) and ordinal not in seen:
            seen.add(ordinal)
            expected.add(ordinal)

    produced = set(alarmed)
    if produced != expected:
        legacy = _legacy_alarmed(events)
        note = ""
        if produced == legacy:
            note = (" — and it is exactly what the OLD tmSeq/seq read produces, "
                    "so the join key was not repaired at all")
        elif expected and produced == {k - 1 for k in expected if k > 1}:
            note = " — the ordinal is being read as 0-based"
        findings.append(finding(
            "D-P4-JOIN-KEY-01",
            f"the scored alarm set is not the registered arrival-ordinal join: "
            f"{len(expected - produced)} expected observations are uncredited, "
            f"{len(produced - expected)} are credited that should not be{note}",
            location))
    return findings

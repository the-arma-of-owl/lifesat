#!/usr/bin/env python3
"""canonical.py -- the producer's CSV rows, typed into the accepted raw-event shape.

The accepted binder (`causal_core.bind_episode`) consumes

    {"event_id": str, "time": float, "category": str, "fields": {...}}

with fields already typed: a sequence number is an int, a voltage is a float, a
link id is an int or the DEFINED JSON null.  The Collector writes strings,
because a CSV writes strings.  This module is the one place where that
conversion happens, and it is a CLOSED map: an unknown category or an unknown
field is an error, never a silent pass-through, so a producer that starts
emitting something new cannot slip past the validator by looking like text.

Nothing is invented here.  Every field below is written by a `logEvent` call in
the C++ sources, and the type is the type that call serialises.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

NULL = "null"          # the producer's spelling of an EXPLICIT null link

# category -> {field: converter}. A category with no entry is refused.
FIELD_TYPES = {
    "pass.start": {"pass": int, "elevationDeg": float},
    "pass.end": {"pass": int, "durationS": float},
    "tm.send": {"seq": int, "vbat": float, "mode": int, "rej": int},
    "tm.recv": {"seq": int, "ageS": float, "vbat": float, "mode": int, "rej": int},
    "tc.send": {"cmdId": int, "seq": int},
    "tc.accept": {"cmdId": int, "seq": int, "type": int},
    "tc.reject": {"cmdId": int, "seq": int, "reason": str},
    "link.drop": {"dir": str, "reason": str},
    "d3.alarm": {
        "channel": str, "physicalBreach": int, "logicalBreach": int,
        "securityBreach": int, "deviationV": float, "boundV": float,
        "dtS": float, "tmSeq": int,
        # PHASE 3 REQUIRED NEW FIELDS. `null` is the producer's spelling of the
        # explicit null the fault signature tests with is_null; it is NOT the
        # same as the field being absent, and the two must stay distinguishable.
        "linkCmdId": "nullable_int", "linkSeq": "nullable_int",
    },
    "d2.alarm": {"n": int},
    "rnd.alarm": {"n": int},
    "update.uplink": {"cmdId": int, "paramKey": str, "paramValue": float},
    "update.blocked": {"paramKey": str, "paramValue": float,
                       "verdict": str, "reason": str},
    "update.unsupported": {"paramKey": str, "paramValue": float,
                           "verdict": str, "reason": str},
    "twin.updateApproved": {"paramKey": str, "paramValue": float,
                            "worstVoltage": float},
    "twin.updateRejected": {"paramKey": str, "paramValue": float,
                            "worstVoltage": float, "floorV": float},
    "twin.updateUnsupported": {"paramKey": str, "paramValue": float, "reason": str},
    "twin.modelUpdated": {"paramKey": str, "paramValue": float, "trigger": str},
}

# The categories the accepted contract actually observes. Everything else is
# carried through into the authority file (it is part of the record) but the
# binder never reads it.
# Truth-row field types. Everything not listed stays a string, which is what
# the accepted validator compares against the pair registry.
TRUTH_INTEGER_FIELDS = {"seed_index", "target_seq", "schedule_duration"}
TRUTH_FLOAT_FIELDS = {"target_send_time", "schedule_onset_offset_s"}

OBSERVED = {"pass.start", "pass.end", "tm.send", "tm.recv", "tc.accept",
            "tc.reject", "link.drop", "d3.alarm"}


class CanonicalError(Exception):
    """A raw event did not type-check against its producer's declared shape."""


def _convert(category, key, value):
    types = FIELD_TYPES.get(category)
    if types is None:
        raise CanonicalError(f"unknown event category {category!r}")
    if key not in types:
        raise CanonicalError(f"{category}: unknown field {key!r}")
    kind = types[key]
    if kind == "nullable_int":
        return None if value == NULL else int(value)
    if kind is str:
        return value
    try:
        return kind(value)
    except ValueError as error:
        raise CanonicalError(f"{category}.{key}={value!r}: {error}") from error


def canonical_events(events, run_id):
    """Types one run's raw events and gives them run-scoped ids."""
    out = []
    for event in events:
        category = event["category"]
        fields = {key: _convert(category, key, value)
                  for key, value in event["fields"].items()}
        out.append({
            "category": category,
            "event_id": f"{run_id}-E{event['index']:05d}",
            "fields": fields,
            "time": event["time"],
        })
    return out


def canonical_truth(truth_rows, run_id):
    """Types one run's truth rows into the accepted truth-authority shape.

    A truth row is audit authority ONLY. It is never consumed as a feature, and
    the leakage test proves that by scrambling every field here and requiring
    the prediction not to move.
    """
    out = []
    for row in truth_rows:
        fields = dict(row["fields"])
        kind = fields.pop("kind", None)
        if kind not in ("episode.begin", "intervention", "episode.end"):
            raise CanonicalError(f"unknown truth row kind {kind!r}")
        typed = {}
        for key, value in fields.items():
            if key in TRUTH_INTEGER_FIELDS:
                typed[key] = None if value == NULL else int(value)
            elif key in TRUTH_FLOAT_FIELDS:
                typed[key] = float(value)
            else:
                # `magnitude`, `variable` and `units` stay STRINGS on purpose.
                # truth_reference_spec.intervention_rule requires them to equal
                # the pair registry's own values exactly, and the registry
                # states magnitude as "+0.150 V", not as a number. Parsing it
                # into a float here would silently make the comparison the
                # validator performs impossible to satisfy.
                typed[key] = value
        out.append({
            "fields": typed,
            "kind": kind,
            "time": row["time"],
            "truth_id": f"{run_id}-T{row['index']:03d}",
        })
    return out

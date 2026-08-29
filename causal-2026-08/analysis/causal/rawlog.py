#!/usr/bin/env python3
"""rawlog.py -- read the REAL producer output, in the producer's own shape.

The simulation writes two CSV files per run through `Collector`:

    <label>-r<N>-events.csv   idx,time,category,fields,prev,chain
    <label>-r<N>-truth.csv    idx,time,fields

`fields` is the Collector's own serialisation: `k=v;k=v;...` (Collector.cc,
`serialise`).  Nothing here invents a second schema: the parser below is the
inverse of that one function, and every test in this package feeds on rows read
by it, so a test can never pass against a shape the producer does not emit.

The event log is hash-chained (HashChain.h).  `verify_chain` recomputes the
chain from the CSV alone, which is what makes the raw event file an authority
rather than a convenience copy.
"""

from __future__ import annotations

import csv
import hashlib
import os
import sys

sys.dont_write_bytecode = True

GENESIS_INPUT = "LIFESAT-GENESIS"


class RawLogError(Exception):
    """A raw log did not have the shape its producer promises."""


def parse_fields(blob):
    """`k=v;k=v` -> dict, exactly inverting Collector::serialise."""
    out = {}
    if blob == "":
        return out
    for item in blob.split(";"):
        if "=" not in item:
            raise RawLogError(f"field item {item!r} carries no '='")
        key, _, value = item.partition("=")
        out[key] = value
    return out


def _rows(path, expected_header):
    if not os.path.exists(path):
        raise RawLogError(f"missing raw log {path}")
    with open(path, newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header != expected_header:
            raise RawLogError(f"{path}: header {header} != {expected_header}")
        # The Collector writes `fields` unquoted and it may itself contain
        # commas only inside a value; it never does, because every value is a
        # number or an identifier.  csv.reader therefore splits correctly, and
        # a row with the wrong arity is a producer defect, not a parser one.
        for line in reader:
            if len(line) != len(expected_header):
                raise RawLogError(f"{path}: row arity {len(line)} != "
                                  f"{len(expected_header)}: {line}")
            yield line


def read_events(path):
    """Returns the ordered raw event rows of one run."""
    events = []
    for idx, time, category, fields, prev, chain in _rows(
            path, ["idx", "time", "category", "fields", "prev", "chain"]):
        events.append({
            "event_id": f"E{int(idx)}",
            "index": int(idx),
            "time": float(time),
            "category": category,
            "fields": parse_fields(fields),
            "prev": prev,
            "chain": chain,
            "raw_record": f"{idx},{time},{category},{fields}",
        })
    return events


def read_truth(path):
    """Returns the ordered raw truth rows of one run.  Audit authority only.

    Parsed with an explicit maxsplit rather than the csv reader.  A truth row's
    `variable` field is the pair registry's own `manipulated_model_variable`
    string, verbatim -- and several of those contain a comma ("downlink telemetry
    payload field batteryVoltage, in transit").  The value has to match the
    registry EXACTLY or D-TRUTH-INTERVENTION-01 fires at the accepting end, so
    the comma cannot be removed; `fields` is the last column, so splitting on
    the first two commas recovers it intact.
    """
    if not os.path.exists(path):
        raise RawLogError(f"missing raw log {path}")
    rows = []
    with open(path, encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n")
        if header != "idx,time,fields":
            raise RawLogError(f"{path}: header {header!r} != 'idx,time,fields'")
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split(",", 2)
            if len(parts) != 3:
                raise RawLogError(f"{path}: malformed truth row {line!r}")
            idx, time, fields = parts
            rows.append({
                "truth_id": f"T{int(idx)}",
                "index": int(idx),
                "time": float(time),
                "fields": parse_fields(fields),
            })
    return rows


def verify_chain(events):
    """Recomputes the hash chain from the CSV alone.

    HashChain.h: head_0 = sha256(GENESIS_INPUT), head_{n+1} = sha256(head_n +
    record).  A verifier that has only the CSV can do this, which is the point.
    """
    head = hashlib.sha256(GENESIS_INPUT.encode()).hexdigest()
    for event in events:
        if event["prev"] != head:
            raise RawLogError(f"{event['event_id']}: prev {event['prev'][:16]} "
                              f"!= running head {head[:16]}")
        head = hashlib.sha256((head + event["raw_record"]).encode()).hexdigest()
        if event["chain"] != head:
            raise RawLogError(f"{event['event_id']}: chain {event['chain'][:16]} "
                              f"!= recomputed {head[:16]}")
    return head


def by_category(events, category):
    return [e for e in events if e["category"] == category]


def run_files(directory, label, run_number=0):
    base = os.path.join(directory, f"{label}-r{run_number}")
    return base + "-events.csv", base + "-truth.csv", base + "-anchor.txt"

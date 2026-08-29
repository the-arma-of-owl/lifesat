"""Run artefacts and the scoring scope / join policy.

Contract: scoring_scope_and_join_policy (run boundaries, warm-up, join keys,
duplicates, unmatched records, timestamp tie-break, malformed/missing files).
Every rule here is fail-closed: absence of evidence is never scored as evidence
of correct behaviour.
"""
import csv
import os
import sys

csv.field_size_limit(sys.maxsize)

RUN_HORIZON = 604800.0


class ArtefactError(AssertionError):
    """Raised when an artefact violates the scope/join policy."""


def parse_fields(text):
    out = {}
    for part in text.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            out[key] = value
    return out


def _rows(path, field_column):
    if not os.path.exists(path):
        raise ArtefactError("missing artefact %s: the run is REJECTED, not skipped"
                            % path)
    out = []
    with open(path, newline="") as handle:
        for raw in csv.reader(handle):
            if not raw or raw[0] == "idx":
                continue
            if len(raw) <= field_column:
                raise ArtefactError("truncated row in %s: the run is REJECTED" % path)
            try:
                idx, t = int(raw[0]), float(raw[1])
            except ValueError as exc:
                raise ArtefactError("malformed row in %s: %s" % (path, exc))
            if t < 0.0 or t > RUN_HORIZON:
                raise ArtefactError("record at t=%r outside [0, %r] in %s: REJECTED"
                                    % (t, RUN_HORIZON, path))
            out.append((idx, t, raw))
    return out


def load_events(path):
    """events.csv rows, ordered by the contract tie-break."""
    rows = [{"idx": i, "t": t, "cat": raw[2], "f": parse_fields(raw[3])}
            for i, t, raw in _rows(path, 3)]
    rows.sort(key=lambda r: (r["t"], r["idx"]))
    seen = set()
    for r in rows:
        if r["cat"] in ("tm.send", "tm.recv"):
            key = (r["cat"], r["f"].get("seq"))
            if key in seen:
                raise ArtefactError("duplicate %s seq=%s in %s: the run is REJECTED"
                                    % (r["cat"], r["f"].get("seq"), path))
            seen.add(key)
    return rows


def load_truth(path):
    """truth.csv rows; the row index is the immutable action identity."""
    rows = [{"idx": i, "t": t, "f": parse_fields(raw[2])}
            for i, t, raw in _rows(path, 2)]
    seen = set()
    for r in rows:
        if r["idx"] in seen:
            raise ArtefactError("duplicate truth row idx=%d in %s: REJECTED"
                                % (r["idx"], path))
        seen.add(r["idx"])
    rows.sort(key=lambda r: (r["t"], r["idx"]))
    return rows


def run_identity(events_path):
    return os.path.basename(events_path).replace("-events.csv", "")


def scenario_of(run):
    return run.split("-")[0]


def of_category(events, category):
    return [r for r in events if r["cat"] == category]


def telemetry_source_time(row):
    """Satellite-side sampling instant: receive time minus the logged age."""
    return row["t"] - float(row["f"].get("ageS", "0"))

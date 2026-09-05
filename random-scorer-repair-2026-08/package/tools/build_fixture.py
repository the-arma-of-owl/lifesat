#!/usr/bin/env python3
"""build_fixture.py — the REAL-SHAPE regression fixture, copied from the corpus.

Plan step 1: "Copy a real `rnd.alarm,n=...` row into regression fixture."

Copied, not written. The fixture carries verbatim CSV lines lifted from a named
run of the immutable corpus, together with that run's path, its manifest digest
and the source line index of every row, so the fixture's realism is checkable
rather than asserted. A fixture someone typed by hand would have reproduced the
bug: `tmSeq` looks plausible until you read what the producer actually emits.

The fixture also carries the two degenerate shapes the defect depended on — a
`tm.recv` row that HAS `seq`, and a `rnd.alarm` row that does NOT have `tmSeq` —
because those are the exact conditions under which the old join silently
produced zeros instead of failing.
"""

from __future__ import annotations

import csv
import os
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import p4_authority as PA  # noqa: E402

FIXTURE_NAME = "RND_ALARM_REGRESSION_FIXTURE.json"
# A real attack cell with the full defence stack, so the fixture exercises a run
# that actually carries truth-positive observations.
FIXTURE_RUN = "A1-D3-s00-r0"
ALARMS_WANTED = 6


def write_json(path, payload):
    import json
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    return PA.sha256_file(path)


def main():
    run = next(r for r in PA.corpus()["runs"] if r["identity"] == FIXTURE_RUN)
    problems = PA.verify_run_inputs(run)
    if problems:
        raise SystemExit(f"fixture source is not the manifest's bytes: {problems}")
    events_path, _truth = PA.run_paths(run)

    with open(events_path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows = list(reader)

    # every tm.recv row, in order, is the join's consumer side
    recv_positions = [i for i, row in enumerate(rows) if row[2] == "tm.recv"]
    alarm_positions = [i for i, row in enumerate(rows) if row[2] == "rnd.alarm"]

    selected = alarm_positions[:ALARMS_WANTED]
    excerpt = []
    for position in selected:
        row = rows[position]
        ordinal = int(dict(kv.split("=", 1)
                           for kv in row[3].split(";") if "=" in kv)["n"])
        observation = rows[recv_positions[ordinal - 1]]
        excerpt.append({
            "alarm_csv_line": ",".join(row),
            "alarm_source_idx": int(row[0]),
            "alarm_time": float(row[1]),
            "declared_ordinal": ordinal,
            "joined_observation_csv_line": ",".join(observation),
            "joined_observation_source_idx": int(observation[0]),
            "joined_observation_time": float(observation[1]),
            "observation_seq_field": dict(
                kv.split("=", 1) for kv in observation[3].split(";")
                if "=" in kv)["seq"],
            "times_equal": abs(float(observation[1]) - float(row[1])) < 1e-9,
        })

    payload = {
        "csv_header": header,
        "defect_preconditions": {
            "alarm_row_has_no_tmSeq_field": all(
                "tmSeq" not in e["alarm_csv_line"] for e in excerpt),
            "observation_row_has_seq_field": all(
                "seq=" in e["joined_observation_csv_line"] for e in excerpt),
            "seq_never_equals_ordinal": all(
                e["observation_seq_field"] != str(e["declared_ordinal"])
                for e in excerpt),
            "statement": (
                "The old join read `tmSeq` off the alarm row (absent -> None) "
                "and compared it against the observation's `seq` (present). "
                "It therefore matched nothing and reported zeros instead of "
                "raising. These three preconditions are what made the failure "
                "silent."),
        },
        "excerpt": excerpt,
        "provenance": {
            "events_sha256": run["events_sha256"],
            "manifest_source": run["source"],
            "run_identity": run["identity"],
            "source_path": events_path,
            "total_alarm_rows_in_run": len(alarm_positions),
            "total_observation_rows_in_run": len(recv_positions),
        },
        "rule": (
            "VERBATIM. Every csv line here is copied byte-for-byte from the "
            "immutable corpus at the recorded source idx. Nothing in this "
            "fixture is synthesised, because a hand-written fixture would have "
            "reproduced the very assumption under test."),
        "schema": "lifesat-v8-phase4-rnd-alarm-fixture/v1",
    }

    path = os.path.join(PA.PHASE4_ROOT, "fixtures", FIXTURE_NAME)
    digest = write_json(path, payload)
    print(f"fixture run              {run['identity']} ({run['source']})")
    print(f"  alarm rows in run      {len(alarm_positions)}")
    print(f"  observation rows       {len(recv_positions)}")
    print(f"  excerpt rows           {len(excerpt)}")
    for key, value in sorted(payload["defect_preconditions"].items()):
        if isinstance(value, bool):
            print(f"  {key:<34} {value}")
    print(f"{FIXTURE_NAME}  {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

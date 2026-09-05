#!/usr/bin/env python3
"""Regression test for the random-detector alarm join.

It fails on the pre-repair join and passes on the repaired one, and it runs
directly against the published raw forensic records without the simulator.

    unzip lifesat-raw-matrix-1200.zip
    LIFESAT_RAW=$PWD/results python3 test_rnd_join_regression.py

Optional: point LIFESAT_SCORER at a scoring package to put the shipped join
itself under test, rather than only the records.

    LIFESAT_RAW=$PWD/results \
    LIFESAT_SCORER=$PWD/random-scorer-repair-2026-08/package/candidate_scorer \
    python3 test_rnd_join_regression.py

What is asserted, per run and then in aggregate:

  A. no `rnd.alarm` row carries a `tmSeq` field. `tmSeq` is what the pre-repair
     consumer read, and the canonical schema declares the row as `{"n": int}`.
  B. the pre-repair recipe therefore credits nothing. Reading `tmSeq` off the
     alarm and comparing it with the observation's `seq` matches zero
     observations, which is the silent failure this test exists to catch.
  C. the repaired recipe credits every alarm row. The k-th `rnd.alarm` of a run
     declares `n == k` and addresses the k-th `tm.recv` row of that run.
  D. the join is witnessed by time. The producer logs `tm.recv` and then calls
     `observe()` inside one call, so the addressed observation must carry the
     alarm's own timestamp.
  E. `seq` is never the arrival ordinal. Spelling the field name correctly
     would still be wrong: `seq` is assigned on the spacecraft and skips on
     in-flight loss, while `n` counts what the ground station observed.
  F. with LIFESAT_SCORER set, the shipped `scoring.rndjoin` reaches the same
     binding as this file's independent recomputation. The two implementations
     are written from the producer source rather than from each other, so an
     agreement here is a check and not an echo. The pre-repair scorer has no
     `rndjoin` module at all and is reported as such.
"""
import argparse
import os
import sys

TOLERANCE_S = 1e-6


def parse_fields(blob):
    out = {}
    for part in blob.split(";"):
        if "=" in part:
            key, _, value = part.partition("=")
            out[key] = value
    return out


def read_events(path):
    """The run as scoring reads it: one dict per row, in idx order."""
    events = []
    with open(path, encoding="utf-8") as handle:
        header = handle.readline()
        if not header.startswith("idx,time,category,fields"):
            raise SystemExit("unexpected header in %s" % path)
        for line in handle:
            parts = line.rstrip("\n").split(",", 4)
            if len(parts) < 4:
                continue
            events.append({"t": float(parts[1]), "cat": parts[2],
                           "f": parse_fields(parts[3])})
    return events


def check_run(events, binder=None):
    observations = [e for e in events if e["cat"] == "tm.recv"]
    alarms = [e for e in events if e["cat"] == "rnd.alarm"]
    failures = []

    # A
    carrying = sum(1 for a in alarms if "tmSeq" in a["f"])
    if carrying:
        failures.append("%d alarm rows carry tmSeq" % carrying)

    # B: the pre-repair recipe, reproduced exactly as it was written
    old_keys = {a["f"].get("tmSeq") for a in alarms}
    old_credited = sum(1 for o in observations if o["f"].get("seq") in old_keys)
    if alarms and old_credited:
        failures.append("pre-repair recipe credited %d observations"
                        % old_credited)

    # C, D, E: the repaired recipe, recomputed here from the producer's rule
    ordinals, seq_equals_n = set(), 0
    for alarm in alarms:
        raw = alarm["f"].get("n")
        try:
            ordinal = int(raw)
        except (TypeError, ValueError):
            failures.append("alarm at t=%r has no usable n" % alarm["t"])
            continue
        if not 1 <= ordinal <= len(observations):
            failures.append("ordinal %d outside 1..%d"
                            % (ordinal, len(observations)))
            continue
        if ordinal in ordinals:
            failures.append("ordinal %d claimed twice" % ordinal)
            continue
        ordinals.add(ordinal)
        observation = observations[ordinal - 1]
        if abs(observation["t"] - alarm["t"]) > TOLERANCE_S:
            failures.append("ordinal %d joined t=%r to an observation at t=%r"
                            % (ordinal, alarm["t"], observation["t"]))
        if observation["f"].get("seq") == raw:
            seq_equals_n += 1

    if len(ordinals) != len(alarms):
        failures.append("repaired recipe bound %d of %d alarm rows"
                        % (len(ordinals), len(alarms)))

    # F: the shipped join, against the recomputation above
    agreed = None
    if binder is not None:
        shipped = binder(events).alarmed_ordinals
        agreed = shipped == ordinals
        if not agreed:
            failures.append("shipped rndjoin bound %d ordinals, this file bound "
                            "%d" % (len(shipped), len(ordinals)))

    return {"alarms": len(alarms), "observations": len(observations),
            "old_credited": old_credited, "bound": len(ordinals),
            "seq_equals_n": seq_equals_n, "agreed": agreed,
            "failures": failures}


def load_binder(scorer_root):
    """The shipped join, or None with the reason it is absent."""
    sys.path.insert(0, scorer_root)
    try:
        from scoring import rndjoin
    except ImportError:
        return None, ("no scoring.rndjoin under %s; a scoring package without "
                      "it is the pre-repair scorer" % scorer_root)
    return rndjoin.bind, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", default=os.environ.get("LIFESAT_RAW", "results"))
    parser.add_argument("--scorer", default=os.environ.get("LIFESAT_SCORER"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not os.path.isdir(args.raw):
        raise SystemExit(
            "set LIFESAT_RAW to the results directory unpacked from\n"
            "lifesat-raw-matrix-1200.zip, for example:\n"
            "  unzip lifesat-raw-matrix-1200.zip\n"
            "  LIFESAT_RAW=$PWD/results python3 test_rnd_join_regression.py")

    binder, binder_note = None, "not requested"
    if args.scorer:
        binder, binder_note = load_binder(os.path.abspath(args.scorer))
        if binder is not None:
            binder_note = None

    files = sorted(name for name in os.listdir(args.raw)
                   if name.endswith("-events.csv"))
    if args.limit:
        files = files[:args.limit]
    if not files:
        raise SystemExit("no *-events.csv under %s" % args.raw)

    totals = {"alarms": 0, "observations": 0, "old_credited": 0,
              "bound": 0, "seq_equals_n": 0}
    disagreed = 0
    failed = []
    for name in files:
        result = check_run(read_events(os.path.join(args.raw, name)), binder)
        for key in totals:
            totals[key] += result[key]
        if result["agreed"] is False:
            disagreed += 1
        for message in result["failures"]:
            failed.append("%s: %s" % (name, message))

    print("runs scanned              : %d" % len(files))
    print("received observations     : %d" % totals["observations"])
    print("raw random-alarm rows     : %d" % totals["alarms"])
    print("pre-repair recipe credited: %d   (must be 0)" % totals["old_credited"])
    print("repaired recipe bound     : %d   (must equal the alarm rows)"
          % totals["bound"])
    print("seq == n                  : %d   (must be 0)" % totals["seq_equals_n"])
    if binder is None:
        print("shipped scoring.rndjoin   : %s" % binder_note)
    else:
        print("shipped scoring.rndjoin   : agreed on %d of %d runs"
              % (len(files) - disagreed, len(files)))

    if totals["alarms"] and totals["bound"] != totals["alarms"]:
        failed.append("aggregate: the repaired recipe did not bind every alarm row")
    if totals["seq_equals_n"]:
        failed.append("aggregate: seq coincided with the arrival ordinal")
    if args.scorer and binder is None:
        failed.append("aggregate: %s" % binder_note)

    if failed:
        print("\nFAIL  %d finding(s)" % len(failed))
        for line in failed[:20]:
            print("  " + line)
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

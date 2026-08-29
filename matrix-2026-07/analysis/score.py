#!/usr/bin/env python3
"""
LIFESAT -- scoring one run: matching detector verdicts against the answer key.

THIS IS THE MEASUREMENT POINT OF THE STUDY.  So far we have looked at raw
alarm counts; the real question is not "how many alarms" but "which alarm
corresponds to which attack".

How R1 is preserved: the answer key (*-truth.csv) is invisible to every detector
during the run. This script runs offline and joins the two files, so scoring
never lets a detector see the key.

Labelling:

  Effect window.  When an attack changes the satellite's state, its effect outlives
  the episode: a tampered parameter stays in force until a legitimate command
  overwrites it.  Alarms are therefore sought in the **effect window**, not in the
  episode window.  Otherwise a detector correctly reporting the state would be
  counted as raising a false alarm.

  For A4 (telemetry side) the effect is a single packet: the modified/delayed
  telemetry itself.  For dropped telemetry no observation is formed at all -- it
  does not enter the point-based metrics and is reported separately.

Metrics (§6 decision, K-59):
  · F0.5   point-based, precision-weighted (a false alarm is expensive for the operator)
  · F1C    event-based recall + point-based precision (composite F-score)
  · FPR    separately, on its own
  F1PA is not used -- the random detector scores 0.912 there (K-59).
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)

DETECTOR_EVENTS = {"d3.alarm": "D3", "d2.alarm": "D2", "rnd.alarm": "RND"}

# Reporting delay of the detector's decision, in seconds.
#
# Without it, event-based matching (F1C) is structurally unfair to window-based
# detectors: D2 decides when its 60 s window closes, while A4's effect interval is a
# single instant. A correct alarm would fall outside the interval and count as a miss.
REPORTING_GRACE = {"D3": 0.0, "D2": 60.0, "RND": 0.0}


def parse_fields(s):
    out = {}
    for part in s.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
    return out


def load_events(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.reader(f):
            if not r or r[0] == "idx":
                continue
            rows.append({"idx": int(r[0]), "t": float(r[1]),
                         "cat": r[2], "f": parse_fields(r[3])})
    return rows


def load_truth(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.reader(f):
            if not r or r[0] == "idx":
                continue
            rows.append({"t": float(r[1]), "f": parse_fields(r[2])})
    return rows


def build_effect_intervals(events, truth, end_time):
    """
    Time intervals over which the attack keeps the satellite's state corrupted.

    Command side (A1/A2/A3): from the moment of acceptance until a legitimate
    command writes the state back.  Telemetry side (A4): a single packet.
    """
    hostile_ids = set()
    tampered_seqs, delayed_seqs, dropped_seqs = set(), set(), set()
    episodes = []
    for r in truth:
        f = r["f"]
        ev = f.get("event")
        if ev == "episode.begin":
            episodes.append({"begin": r["t"], "end": None})
        elif ev == "episode.end" and episodes:
            episodes[-1]["end"] = r["t"]
        elif ev in ("inject", "replay") and "cmdId" in f:
            hostile_ids.add(f["cmdId"])
        elif ev == "tamper" and f.get("field") == "paramValue":
            hostile_ids.add(f["cmdId"])
        elif ev == "tamper" and f.get("field") == "batteryVoltage":
            tampered_seqs.add(f["tmSeq"])
        elif ev == "delay":
            delayed_seqs.add(f["tmSeq"])
        elif ev == "drop":
            dropped_seqs.add(f["tmSeq"])
    for e in episodes:
        if e["end"] is None:
            e["end"] = end_time

    accepts = [(r["t"], r["f"].get("cmdId")) for r in events if r["cat"] == "tc.accept"]
    rejects = [(r["t"], r["f"].get("cmdId")) for r in events if r["cat"] == "tc.reject"]
    recv_times = sorted(r["t"] for r in events if r["cat"] == "tm.recv")
    intervals = []

    # with D1 on, a hostile command is rejected rather than accepted, so the satellite
    # state is not corrupted. the attack still happened and leaves an observable trace:
    # the rejected-command counter rises. the detection opportunity is that moment.
    for t_rej, cid in rejects:
        if cid not in hostile_ids:
            continue
        nxt = next((x for x in recv_times if x > t_rej), end_time)
        intervals.append((t_rej, nxt + 1e-6))
    for i, (t, cid) in enumerate(accepts):
        if cid not in hostile_ids:
            continue
        # the next legitimate acceptance writes the state back and ends the effect
        stop = end_time
        for t2, cid2 in accepts[i + 1:]:
            if cid2 not in hostile_ids:
                stop = t2
                break
        intervals.append((t, stop))

    # A4: single-packet effect -- the instant the telemetry is received
    recv = {r["f"].get("seq"): r["t"] for r in events if r["cat"] == "tm.recv"}
    point_effects = set()
    for seq in tampered_seqs | delayed_seqs:
        if seq in recv:
            point_effects.add(recv[seq])
            intervals.append((recv[seq] - 1e-9, recv[seq] + 1e-9))

    return {"intervals": sorted(intervals), "episodes": episodes,
            "hostileCommands": len(hostile_ids),
            "tamperedTm": len(tampered_seqs), "delayedTm": len(delayed_seqs),
            "droppedTm": len(dropped_seqs), "pointEffects": point_effects}


def in_any(t, intervals):
    for a, b in intervals:
        if a <= t <= b:
            return True
    return False


def score_detector(events, truth_info, detector, end_time, grace=None):
    intervals = truth_info["intervals"]
    obs = [r["t"] for r in events if r["cat"] == "tm.recv"]
    alarms = [r["t"] for r in events
              if DETECTOR_EVENTS.get(r["cat"]) == detector]

    # point-based
    labelled = {t: in_any(t, intervals) for t in obs}
    alarmed = set()
    for a in alarms:
        # bind the alarm to the observation that triggered it (same or nearest earlier)
        best = None
        for t in obs:
            if t <= a + 1e-6 and (best is None or t > best):
                best = t
        if best is not None:
            alarmed.add(best)

    tp = sum(1 for t in obs if labelled[t] and t in alarmed)
    fp = sum(1 for t in obs if not labelled[t] and t in alarmed)
    fn = sum(1 for t in obs if labelled[t] and t not in alarmed)
    tn = sum(1 for t in obs if not labelled[t] and t not in alarmed)

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    b2 = 0.25          # F0.5
    f05 = ((1 + b2) * precision * recall / (b2 * precision + recall)
           if (b2 * precision + recall) else 0.0)

    # event-based (F1C)
    # an attack event counts as caught if at least one alarm falls inside its effect
    # interval.
    detected, delays = 0, []
    g = REPORTING_GRACE.get(detector, 0.0) if grace is None else grace
    for a, b in intervals:
        # the reporting grace period counts as well (see REPORTING_GRACE)
        hits = [x for x in alarms if a <= x <= b + g]
        if hits:
            detected += 1
            delays.append(min(hits) - a)
    n_events = len(intervals)
    recall_c = detected / n_events if n_events else 0.0
    f1c = (2 * precision * recall_c / (precision + recall_c)
           if (precision + recall_c) else 0.0)

    return {"detector": detector, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "fpr": fpr,
            "f05": f05, "recallEvent": recall_c, "f1c": f1c,
            "events": n_events, "detectedEvents": detected,
            "reportingGrace": g,
            "meanDetectionDelay": sum(delays) / len(delays) if delays else None,
            "observations": len(obs), "alarms": len(alarms)}


def score_run(events_path, truth_path, end_time):
    events = load_events(events_path)
    truth = load_truth(truth_path)
    info = build_effect_intervals(events, truth, end_time)
    out = {"truth": {k: v for k, v in info.items()
                     if k not in ("intervals", "episodes", "pointEffects")},
           "episodes": len(info["episodes"]),
           "effectIntervals": len(info["intervals"])}
    for d in ("D3", "D2", "RND"):
        out[d] = score_detector(events, info, d, end_time)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("--truth", default=None)
    ap.add_argument("--end", type=float, default=604800.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    truth = args.truth or args.events.replace("-events.csv", "-truth.csv")
    r = score_run(args.events, truth, args.end)

    if args.json:
        print(json.dumps(r, indent=2))
        return 0

    t = r["truth"]
    print(f"\nanswer key: {r['episodes']} episodes · {t['hostileCommands']} hostile commands · "
          f"{t['tamperedTm']} tampered TM · {t['delayedTm']} delayed · {t['droppedTm']} dropped")
    print(f"effect windows: {r['effectIntervals']}\n")
    print(f"{'detector':<10}{'TP':>5}{'FP':>5}{'FN':>5}{'precision':>11}{'recall':>9}"
          f"{'FPR':>8}{'F0.5':>8}{'F1C':>8}{'delay':>10}")
    print("-" * 78)
    for d in ("D3", "D2", "RND"):
        s = r[d]
        dl = f"{s['meanDetectionDelay']:.0f} s" if s["meanDetectionDelay"] is not None else " -- "
        print(f"{d:<10}{s['tp']:>5}{s['fp']:>5}{s['fn']:>5}{s['precision']:>10.3f}"
              f"{s['recall']:>9.3f}{s['fpr']:>8.4f}{s['f05']:>8.3f}{s['f1c']:>8.3f}{dl:>10}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

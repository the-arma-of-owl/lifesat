#!/usr/bin/env python3
"""Contract-conformant reference implementation ("oracle") for LIFESAT scoring.

Implements the normative rules of scoring-contract-v1 (candidate version
1.4.3-candidate; the 1.4.2 seal remains the historical authority). The RED tests
CURRENT scorer (analysis/score.py) against this oracle; every disagreement is a
known defect the contract requires to be corrected.

This module is TEST-ONLY. It is not the corrected scorer and must not be used to
produce published results.
"""
import csv
import glob
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict

csv.field_size_limit(sys.maxsize)

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(os.path.dirname(HERE))              # .../simulation
RESULTS = os.path.join(SIM, "results")
SPECS = os.path.join(SIM, "specs")
CONTRACT_JSON = os.path.join(SPECS, "scoring-contract-v1.json")

ACCEPTED_CONTRACT_SHA256 = \
    "913848492f82502f5a28243534eaa3e2e19c3c023ebd8b49df8027b8ccf54e95"
ACCEPTED_CONTRACT_VERSION = "1.4.3-candidate"


# ---------------------------------------------------------------------------
# contract access
# ---------------------------------------------------------------------------
def contract():
    with open(CONTRACT_JSON, "rb") as fh:
        raw = fh.read()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != ACCEPTED_CONTRACT_SHA256:
        raise AssertionError(
            "the contract on disk is not the accepted package: sha256 %s != accepted %s"
            % (digest, ACCEPTED_CONTRACT_SHA256))
    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------------------
# artefact loading
# ---------------------------------------------------------------------------
def parse_fields(s):
    out = {}
    for part in s.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
    return out


def load_events(path):
    rows = []
    with open(path, newline="") as fh:
        for r in csv.reader(fh):
            if not r or r[0] == "idx":
                continue
            rows.append({"idx": int(r[0]), "t": float(r[1]), "cat": r[2],
                         "f": parse_fields(r[3])})
    return rows


def load_truth(path):
    rows = []
    with open(path, newline="") as fh:
        for r in csv.reader(fh):
            if not r or r[0] == "idx":
                continue
            rows.append({"idx": int(r[0]), "t": float(r[1]), "f": parse_fields(r[2])})
    return rows


def run_paths(pattern):
    """Yield (run_identity, events_path, truth_path) for a glob over results/."""
    for ep in sorted(glob.glob(os.path.join(RESULTS, pattern))):
        run = os.path.basename(ep).replace("-events.csv", "")
        yield run, ep, ep.replace("-events.csv", "-truth.csv")


# ---------------------------------------------------------------------------
# raw_event_mapping (contract B0)
# ---------------------------------------------------------------------------
HOSTILE_TRUTH_EVENT = {"A1": "tamper", "A2": "inject", "A2v": "tamper", "A3": "replay"}
PROVENANCE_EVENTS = {"attacker.armed", "episode.begin", "episode.end", "capture"}


def attack_action_id(run, truth_idx):
    """attack_action_id = run_identity + immutable truth row index."""
    return "%s#truth:%d" % (run, truth_idx)


# ---------------------------------------------------------------------------
# matching_policy (contract B1) - no global time constant
# ---------------------------------------------------------------------------
def match_actions_to_outcomes(run, events, truth, scenario):
    """Return list of dicts: one per hostile command action.

    Fields: action_id, truth_idx, t, cmd_id, outcome ('accept'|'reject'|None),
            outcome_t, outcome_row_idx, delivered (bool).
    Policy is selected from the per-run identity-uniqueness precondition.
    """
    ev = HOSTILE_TRUTH_EVENT.get(scenario)
    acts = [r for r in truth if r["f"].get("event") == ev and "cmdId" in r["f"]]
    ids = [r["f"]["cmdId"] for r in acts]
    unique = len(set(ids)) == len(ids)

    outcomes = defaultdict(list)
    for r in events:
        if r["cat"] in ("tc.accept", "tc.reject"):
            outcomes[r["f"].get("cmdId")].append(r)
    for v in outcomes.values():
        v.sort(key=lambda r: (r["t"], r["idx"]))

    by_id = defaultdict(list)
    for r in acts:
        by_id[r["f"]["cmdId"]].append(r["t"])
    for v in by_id.values():
        v.sort()

    claimed = set()
    out = []
    for r in acts:
        cid = r["f"]["cmdId"]
        rec = {"action_id": attack_action_id(run, r["idx"]), "truth_idx": r["idx"],
               "t": r["t"], "cmd_id": cid, "outcome": None, "outcome_t": None,
               "outcome_row_idx": None, "policy":
                   "identity_unique_exact_match" if unique
                   else "monotone_forward_one_to_one_bounded_by_next_action"}
        if unique:
            cands = outcomes.get(cid, [])
            if len(cands) == 1:
                hit = cands[0]
            else:
                hit = next((c for c in cands if c["t"] >= r["t"]), None)
        else:
            later = [x for x in by_id[cid] if x > r["t"]]
            bound = later[0] if later else float("inf")
            hit = None
            for j, c in enumerate(outcomes.get(cid, [])):
                if (cid, j) in claimed or c["t"] < r["t"] or c["t"] >= bound:
                    continue
                claimed.add((cid, j))
                hit = c
                break
        if hit is not None:
            rec["outcome"] = "accept" if hit["cat"] == "tc.accept" else "reject"
            rec["outcome_t"] = hit["t"]
            rec["outcome_row_idx"] = hit["idx"]
        rec["delivered"] = rec["outcome"] is not None
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# idempotency (contract B0c): value law from GroundStation.cc:98
# ---------------------------------------------------------------------------
def gain_of(cmd_id):
    """paramValue = 1.0 + 0.1 * (commandId mod 5); the single key is `gain`."""
    return 1.0 + 0.1 * (int(cmd_id) % 5)


def classify_accepted(run, events, matched):
    """Classify each accepted hostile command as state_changed or idempotent.

    Replays the whole accepted-command stream chronologically, maintaining the
    prevailing value of the single parameter key.
    """
    hostile_rows = {m["outcome_row_idx"] for m in matched if m["outcome"] == "accept"}
    accepts = sorted([r for r in events if r["cat"] == "tc.accept"],
                     key=lambda r: (r["t"], r["idx"]))
    prevailing = None
    verdict = {}
    for r in accepts:
        g = gain_of(r["f"]["cmdId"])
        if r["idx"] in hostile_rows:
            if prevailing is not None and abs(g - prevailing) < 1e-12:
                verdict[r["idx"]] = "accepted_idempotent_no_change"
            else:
                verdict[r["idx"]] = "state_changed"
        prevailing = g
    return verdict


def effect_windows(run, events, matched, end_time=604800.0):
    """Effect windows for accepted hostile commands that changed state.

    Closing rule (single normative source,
    effect_event_definition.effect_window_closing_rule):
      next accepted command, legitimate or hostile, that writes a DIFFERENT value
      to the same key; an idempotent write neither closes nor opens a window.
    """
    verdict = classify_accepted(run, events, matched)
    accepts = sorted([r for r in events if r["cat"] == "tc.accept"],
                     key=lambda r: (r["t"], r["idx"]))
    windows = []
    for i, r in enumerate(accepts):
        if verdict.get(r["idx"]) != "state_changed":
            continue
        value = gain_of(r["f"]["cmdId"])
        stop = end_time
        for nxt in accepts[i + 1:]:
            if abs(gain_of(nxt["f"]["cmdId"]) - value) >= 1e-12:
                stop = nxt["t"]
                break
        windows.append({"action_row_idx": r["idx"], "start": r["t"], "stop": stop,
                        "value": value})
    return windows


# ---------------------------------------------------------------------------
# D2 window semantics (contract B5)
# ---------------------------------------------------------------------------
def observation_window(t):
    """k = ceil(t/60); window 1 = [0,60]; window k>=2 = (60(k-1), 60k]."""
    if t <= 0:
        return 1
    return max(1, math.ceil(t / 60.0 - 1e-12))


def expected_arrival_window(send_t):
    """k = floor(s/60)+1, the observation window containing s + delta."""
    return int(send_t // 60) + 1


def d2_decision_units(events):
    """Non-empty windows are the D2 decision opportunities; alarms mark positives."""
    nonempty = {observation_window(r["t"]) for r in events if r["cat"] == "tm.recv"}
    alarms = {observation_window(r["t"]) for r in events if r["cat"] == "d2.alarm"}
    return nonempty, alarms


# ---------------------------------------------------------------------------
# A4 accounting (contract E)
# ---------------------------------------------------------------------------
def a4_dispositions(events, truth):
    send = {r["f"].get("seq"): r["t"] for r in events if r["cat"] == "tm.send"}
    recv = {r["f"].get("seq"): r["t"] for r in events if r["cat"] == "tm.recv"}
    out = Counter()
    per_action = []
    for r in truth:
        ev = r["f"].get("event")
        if ev not in ("tamper", "delay", "drop"):
            continue
        q = r["f"].get("tmSeq")
        if ev == "tamper":
            d = "received_modified" if q in recv else "unresolved"
        elif ev == "delay":
            d = "received_delayed" if q in recv else "unresolved"
        else:
            d = "dropped" if (q in send and q not in recv) else "unresolved"
        out[d] += 1
        per_action.append({"truth_idx": r["idx"], "subtype": ev, "tmSeq": q,
                           "disposition": d})
    return out, per_action


def a4_window_mappings(events, truth):
    """Action -> D2 window mappings, and the deduplicated unique window set."""
    send = {r["f"].get("seq"): r["t"] for r in events if r["cat"] == "tm.send"}
    recv = {r["f"].get("seq"): r["t"] for r in events if r["cat"] == "tm.recv"}
    nonempty, _ = d2_decision_units(events)
    mappings = []
    for r in truth:
        ev = r["f"].get("event")
        if ev not in ("delay", "drop"):
            continue          # modification is not flow-observable
        q = r["f"].get("tmSeq")
        s = send.get(q)
        if s is None:
            continue
        we = expected_arrival_window(s)
        if ev == "drop":
            if we in nonempty:
                mappings.append(("drop_expected", we, r["idx"]))
        else:
            mappings.append(("delay_expected", we, r["idx"]))
            rt = recv.get(q)
            if rt is not None:
                wa = observation_window(rt)
                if wa != we:
                    mappings.append(("delay_eventual", wa, r["idx"]))
    unique = {m[1] for m in mappings}
    return mappings, unique


def a4_drop_opportunity_classes(events, truth):
    send = {r["f"].get("seq"): r["t"] for r in events if r["cat"] == "tm.send"}
    nonempty, _ = d2_decision_units(events)
    out = Counter()
    for r in truth:
        if r["f"].get("event") != "drop":
            continue
        s = send.get(r["f"].get("tmSeq"))
        if s is None:
            out["unresolved"] += 1
            continue
        we = expected_arrival_window(s)
        out["native_decision_opportunity" if we in nonempty
            else "no_native_decision_opportunity"] += 1
    return out


# ---------------------------------------------------------------------------
# F4 evidence events (contract B6)
# ---------------------------------------------------------------------------
def f4_evidence_events(run, events, truth, scenario):
    """D1 rejection evidence events with source-time eligibility."""
    matched = match_actions_to_outcomes(run, events, truth, scenario)
    rejections = sorted([m["outcome_t"] for m in matched if m["outcome"] == "reject"])
    obs = []
    for r in events:
        if r["cat"] != "tm.recv":
            continue
        age = float(r["f"].get("ageS", "0"))
        obs.append({"recv": r["t"], "src": r["t"] - age, "seq": r["f"].get("seq"),
                    "rej": int(r["f"].get("rej", "0")), "idx": r["idx"]})
    obs.sort(key=lambda o: (o["src"], o["seq"], o["idx"]))
    alarms = {r["f"].get("tmSeq") for r in events if r["cat"] == "d3.alarm"}

    out = Counter()
    per_event = []
    for rt in rejections:
        eligible = [o for o in obs if o["src"] > rt]
        if not eligible:
            out["no_reporting_opportunity"] += 1
            per_event.append({"rejection_t": rt, "outcome": "no_reporting_opportunity"})
            continue
        o = eligible[0]
        outcome = "reported" if o["seq"] in alarms else "not_reported"
        out[outcome] += 1
        out["denominator_eligible"] += 1
        per_event.append({"rejection_t": rt, "outcome": outcome, "obs_seq": o["seq"]})
    return out, per_event


def observed_rej_transitions(events):
    """The RETRACTED circular denominator, kept only for comparison."""
    prev = None
    n = 0
    for r in sorted([x for x in events if x["cat"] == "tm.recv"],
                    key=lambda x: (x["t"], x["idx"])):
        cur = int(r["f"].get("rej", "0"))
        if prev is not None and cur != prev:
            n += 1
        prev = cur
    return n


# ---------------------------------------------------------------------------
# corpus helpers
# ---------------------------------------------------------------------------
def scenario_of(run):
    return run.split("-")[0]


def corpus(pattern):
    """Load a whole glob once; returns list of (run, events, truth)."""
    out = []
    for run, ep, tp in run_paths(pattern):
        out.append((run, load_events(ep), load_truth(tp)))
    return out

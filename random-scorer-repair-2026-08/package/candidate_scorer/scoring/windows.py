"""Window semantics for the flow detector.

Contract: window_semantics. The interval and the index formula agree at exact
boundaries; the expected-arrival window is a separate rule; the decision unit is
(run_identity, window_index) and is never replicated per observation.
"""
import math

WINDOW_SECONDS = 60.0


def observation_window(t):
    """k = ceil(t/60); window 1 = [0,60]; window k>=2 = (60(k-1), 60k]."""
    if t <= 0.0:
        return 1
    return max(1, int(math.ceil(t / WINDOW_SECONDS - 1e-12)))


def expected_arrival_window(send_t):
    """Window containing s + delta, closed form k = floor(s/60) + 1."""
    return int(send_t // WINDOW_SECONDS) + 1


def assert_no_boundary_observation(events):
    """Fail-closed precondition: the same-time convention is unexercised."""
    unresolved = []
    for r in events:
        if r["cat"] != "tm.recv":
            continue
        k = r["t"] / WINDOW_SECONDS
        if abs(k - round(k)) < 1e-12:
            unresolved.append(r["f"].get("seq"))
    return unresolved


def decision_set(events):
    """Non-empty windows are D2 decision opportunities; alarms mark positives."""
    opportunities = {observation_window(r["t"]) for r in events
                     if r["cat"] == "tm.recv"}
    alarms = {observation_window(r["t"]) for r in events if r["cat"] == "d2.alarm"}
    return opportunities, alarms


def flow_observable_mappings(events, telemetry_actions):
    """Action -> window mappings for flow-observable A4 consequences.

    Telemetry modification alters none of the three statistics FlowDetector
    measures, so it never makes a window truth-positive. A delayed packet maps to
    TWO distinct units: its expected-arrival window and, when different, its
    eventual-receive window.
    """
    sent = {r["f"].get("seq"): r["t"] for r in events if r["cat"] == "tm.send"}
    received = {r["f"].get("seq"): r["t"] for r in events if r["cat"] == "tm.recv"}
    opportunities, _ = decision_set(events)
    mappings = []
    for a in telemetry_actions:
        if a["action"] not in ("delay_telemetry", "drop_telemetry"):
            continue
        send_t = sent.get(a["tm_seq"])
        if send_t is None:
            continue
        expected = expected_arrival_window(send_t)
        if a["action"] == "drop_telemetry":
            if expected in opportunities:
                mappings.append({"kind": "drop_expected", "window": expected,
                                 "truth_idx": a["truth_idx"]})
            continue
        mappings.append({"kind": "delay_expected", "window": expected,
                         "truth_idx": a["truth_idx"]})
        recv_t = received.get(a["tm_seq"])
        if recv_t is not None:
            eventual = observation_window(recv_t)
            if eventual != expected:
                mappings.append({"kind": "delay_eventual", "window": eventual,
                                 "truth_idx": a["truth_idx"]})
    return mappings


def drop_opportunity_classes(events, telemetry_actions):
    """Each drop is classified by whether D2 had a decision opportunity at all."""
    sent = {r["f"].get("seq"): r["t"] for r in events if r["cat"] == "tm.send"}
    opportunities, alarm_windows = decision_set(events)
    classes = {"native_decision_opportunity": 0,
               "no_native_decision_opportunity": 0, "unresolved": 0}
    covered = 0
    for a in telemetry_actions:
        if a["action"] != "drop_telemetry":
            continue
        send_t = sent.get(a["tm_seq"])
        if send_t is None:
            classes["unresolved"] += 1
            continue
        window = expected_arrival_window(send_t)
        if window in opportunities:
            classes["native_decision_opportunity"] += 1
            # EST-A4-L3-02: within the native class, was the drop's
            # expected-arrival window one where D2 actually alarmed? The unit
            # here is the ATTACK ACTION; the (run_identity, window_index) dedup
            # that defines a D2 decision unit is untouched, so two drops sharing
            # one window remain two actions and one window.
            if window in alarm_windows:
                covered += 1
        else:
            classes["no_native_decision_opportunity"] += 1
    classes["covered_by_alarming_expected_arrival_window"] = covered
    classes["numerator"] = covered
    classes["denominator"] = classes["native_decision_opportunity"]
    return classes

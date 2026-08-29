"""Spacecraft parameter state, idempotency and effect windows.

Contract: idempotency_semantics (value law and offline reconstruction),
effect_event_definition (constituents, closing rule, one-alarm-one-event dedup).
"""


TOLERANCE = 1e-12
PARAM_KEY = "gain"

STATE_CHANGED = "state_changed"
IDEMPOTENT = "accepted_idempotent_no_change"
PREVENTED = "no_state_change_prevented"
NOT_DELIVERED = "no_state_change_not_delivered"
TELEMETRY_ONLY = "telemetry_only_no_state_change"


def written_value(wire_id):
    """GroundStation.cc:98 - paramValue = 1.0 + 0.1 * (commandId mod 5).

    Every generated telecommand writes the single key `gain`, so the parameter
    store has one slot and the prevailing value is a scalar function of cmdId.
    """
    return 1.0 + 0.1 * (int(wire_id) % 5)


def accepted_stream(events):
    return sorted((r for r in events if r["cat"] == "tc.accept"),
                  key=lambda r: (r["t"], r["idx"]))


def replay_parameter_store(events, hostile_rows):
    """Walk the accepted commands in order, tracking the prevailing value.

    Returns {events_row_idx: STATE_CHANGED | IDEMPOTENT} for hostile acceptances.
    """
    prevailing = None
    verdicts = {}
    for row in accepted_stream(events):
        value = written_value(row["f"]["cmdId"])
        if row["idx"] in hostile_rows:
            if prevailing is not None and abs(value - prevailing) < TOLERANCE:
                verdicts[row["idx"]] = IDEMPOTENT
            else:
                verdicts[row["idx"]] = STATE_CHANGED
        prevailing = value
    return verdicts


def spacecraft_effect(record, verdicts):
    if not record["delivered"]:
        return NOT_DELIVERED
    if record["outcome"] == "rejected":
        return PREVENTED
    return verdicts.get(record["outcome_row"], STATE_CHANGED)


def effect_windows(events, verdicts, horizon):
    """Windows for hostile acceptances that actually changed state.

    Closing rule (single normative source): the next accepted command,
    legitimate or hostile, that writes a DIFFERENT value to the same key. An
    idempotent write neither closes nor opens a window.
    """
    stream = accepted_stream(events)
    windows = []
    for pos, row in enumerate(stream):
        if verdicts.get(row["idx"]) != STATE_CHANGED:
            continue
        value = written_value(row["f"]["cmdId"])
        stop = horizon
        for later in stream[pos + 1:]:
            if abs(written_value(later["f"]["cmdId"]) - value) >= TOLERANCE:
                stop = later["t"]
                break
        windows.append({"kind": "accepted_hostile_command_effect",
                        "source_row": row["idx"], "start": row["t"], "stop": stop,
                        "value": value})
    return windows


def telemetry_effect_events(events, telemetry_actions):
    """Point effect events for received tampered/delayed telemetry."""
    received = {r["f"].get("seq"): r["t"] for r in events if r["cat"] == "tm.recv"}
    out = []
    for a in telemetry_actions:
        if a["action"] == "tamper_telemetry":
            kind = "received_modified_observation_effect"
        elif a["action"] == "delay_telemetry":
            kind = "received_delayed_observation_effect"
        else:
            continue                      # a drop produces no observation
        t = received.get(a["tm_seq"])
        if t is None:
            continue
        out.append({"kind": kind, "source_row": a["truth_idx"], "start": t,
                    "stop": t, "tm_seq": a["tm_seq"]})
    return out


def credit_alarms(alarm_times, effect_events):
    """One alarm credits AT MOST ONE effect event (earliest unclaimed)."""
    claimed = set()
    for a in sorted(alarm_times):
        for i, e in enumerate(effect_events):
            if i in claimed:
                continue
            if e["start"] - 1e-9 <= a <= e["stop"] + 1e-9:
                claimed.add(i)
                break
    return len(claimed), claimed

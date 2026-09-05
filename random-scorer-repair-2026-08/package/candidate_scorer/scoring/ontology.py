"""Raw-event mapping and attack identity.

Contract: raw_event_mapping (the raw `event` string is never the enum value),
attack_action_id, truth_provenance_event, attack_subtype.
"""
from .artefacts import ArtefactError

PROVENANCE = {"attacker.armed": "attacker_armed",
              "episode.begin": "episode_begin",
              "episode.end": "episode_end",
              "capture": "capture"}

# (raw event, scenario, field) -> attack_action enum value
_ACTION_RULES = (
    ("inject", None, None, "inject"),
    ("replay", None, None, "replay"),
    ("tamper", "A1", "paramValue", "tamper_command_parameter"),
    ("tamper", "A2v", "paramValue", "tamper_command_parameter"),
    ("tamper", "A4", "batteryVoltage", "tamper_telemetry"),
    ("tamper", "A7c", "rejectedCmdCount", "tamper_security_counter"),
    ("delay", "A4", None, "delay_telemetry"),
    ("drop", "A4", None, "drop_telemetry"),
    ("spoof", "A8", None, "spoof_physical_measurement"),
)

TIER1_ACTIONS = frozenset({"inject", "replay", "tamper_command_parameter",
                           "tamper_telemetry", "delay_telemetry", "drop_telemetry"})

COMMAND_SIDE = frozenset({"inject", "replay", "tamper_command_parameter"})
TELEMETRY_SIDE = frozenset({"tamper_telemetry", "delay_telemetry", "drop_telemetry"})


def classify(row, scenario):
    """Map one truth row to (kind, value); kind is 'action' or 'provenance'."""
    event = row["f"].get("event")
    if event in PROVENANCE:
        return "provenance", PROVENANCE[event]
    field = row["f"].get("field")
    for raw, scope, want_field, value in _ACTION_RULES:
        if raw != event:
            continue
        if scope is not None and scope != scenario:
            continue
        if want_field is not None and want_field != field:
            continue
        return "action", value
    raise ArtefactError(
        "truth row idx=%d matches no raw_event_mapping rule "
        "(event=%r scenario=%r field=%r): the run is REJECTED"
        % (row["idx"], event, scenario, field))


def attack_action_id(run, truth_idx):
    """Identity derived from immutable artefacts; never the on-wire cmdId."""
    return "%s#truth:%d" % (run, truth_idx)


def actions(run, truth, scenario):
    """Every truth row that maps to an attack_action, with its own identity."""
    out = []
    for row in truth:
        kind, value = classify(row, scenario)
        if kind != "action":
            continue
        out.append({"action_id": attack_action_id(run, row["idx"]),
                    "truth_idx": row["idx"], "t": row["t"], "action": value,
                    "wire_id": row["f"].get("cmdId"),
                    "tm_seq": row["f"].get("tmSeq"), "fields": row["f"]})
    return out

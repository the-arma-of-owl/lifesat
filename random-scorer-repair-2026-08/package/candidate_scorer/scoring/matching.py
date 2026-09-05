"""Action-to-outcome matching.

Contract: matching_policy. No global time-window constant exists anywhere; the
policy is selected per run from a verifiable identity-uniqueness precondition.
"""
from collections import defaultdict

from .ontology import COMMAND_SIDE

EXACT = "identity_unique_exact_match"
MONOTONE = "monotone_forward_one_to_one_bounded_by_next_action"


def select_policy(command_actions):
    ids = [a["wire_id"] for a in command_actions]
    return EXACT if len(set(ids)) == len(ids) else MONOTONE


def match(events, command_actions):
    """Attach the D1 outcome to each command-side action.

    Returns the action list enriched with: policy, delivered, outcome
    ('accepted'/'rejected'/None), outcome_t, outcome_row, reject_reason.
    Events preceding the first action of an identity are never claimed, so the
    original legitimate uplink of a replayed command stays benign.
    """
    policy = select_policy(command_actions)
    outcomes = defaultdict(list)
    for row in events:
        if row["cat"] in ("tc.accept", "tc.reject"):
            outcomes[row["f"].get("cmdId")].append(row)
    for rows in outcomes.values():
        rows.sort(key=lambda r: (r["t"], r["idx"]))

    action_times = defaultdict(list)
    for a in command_actions:
        action_times[a["wire_id"]].append(a["t"])
    for times in action_times.values():
        times.sort()

    claimed = set()
    enriched = []
    for a in sorted(command_actions, key=lambda x: (x["t"], x["truth_idx"])):
        wire = a["wire_id"]
        hit = None
        if policy == EXACT:
            candidates = outcomes.get(wire, [])
            if len(candidates) == 1:
                hit = candidates[0]
            else:
                hit = next((c for c in candidates if c["t"] >= a["t"]), None)
        else:
            later = [t for t in action_times[wire] if t > a["t"]]
            bound = later[0] if later else float("inf")
            for pos, cand in enumerate(outcomes.get(wire, [])):
                if (wire, pos) in claimed:
                    continue
                if cand["t"] < a["t"] or cand["t"] >= bound:
                    continue
                claimed.add((wire, pos))
                hit = cand
                break
        rec = dict(a)
        rec["policy"] = policy
        if hit is None:
            rec.update({"delivered": False, "outcome": None, "outcome_t": None,
                        "outcome_row": None, "reject_reason": None})
        else:
            rec.update({
                "delivered": True,
                "outcome": "accepted" if hit["cat"] == "tc.accept" else "rejected",
                "outcome_t": hit["t"], "outcome_row": hit["idx"],
                "reject_reason": hit["f"].get("reason")})
        enriched.append(rec)
    return enriched, policy


def command_actions_of(action_records):
    return [a for a in action_records if a["action"] in COMMAND_SIDE]

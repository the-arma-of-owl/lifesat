"""rndjoin.py — the random detector's producer→consumer join, registered.

THE DEFECT THIS REPLACES (V7-N-132, V7-N-135)
---------------------------------------------
The producer emits, once per observation on which it fired:

    collector->logEvent("rnd.alarm", {{"n", std::to_string(observations)}});
                                        └── src/RandomDetector.cc:27

The consumer read a field that does not exist on that row:

    alarmed = {r["f"].get("tmSeq") for r in events if r["cat"] == "rnd.alarm"}
    has_alarm = row["f"].get("seq") in alarmed

`tmSeq` is absent from every `rnd.alarm` row, so `alarmed` collapsed to `{None}`
and `has_alarm` was False for every observation that carried a `seq`. The random
detector therefore scored as a detector that never fires: tp = fp = 0, every
truth positive fell to fn, every negative to tn.

The error is TWO errors, and fixing only the first would still be wrong:

  1. WRONG FIELD NAME — `tmSeq` is not emitted; `n` is.
  2. WRONG UNIT       — even spelled correctly, a telemetry SEQUENCE NUMBER is
     not an ARRIVAL ORDINAL. `seq` is assigned on the satellite and skips
     whenever a packet is lost in flight; `n` counts what the ground station
     actually observed. Recounted from the raw CSV of the accepted corpus, `seq`
     equals `n` for NOT ONE alarm — they are never interchangeable, not even by
     accident:

         ACCEPTED-CORPUS RAW RANDOM-ALARM ROWS: 9812 over 1200 runs; seq == n in 0

     That line is the canonical claim form. `tools/p4_rawtotals.py` re-derives
     every number in it from the raw CSV and fails the validation if this
     docstring disagrees, because a total nothing recomputes is a total that
     goes stale.

THE JOIN
--------
`GroundStation::handleTelemetry` logs `tm.recv` and THEN calls
`randomDet->observe()`, in that order, in the same call:

    collector->logEvent("tm.recv", {{"seq", ...}, ...});   // GroundStation.cc:195
    ...
    if (randomDet) randomDet->observe();                    // GroundStation.cc:204

`observe()` increments `observations` before deciding, so the k-th `observe()`
call carries `n == k` and corresponds to the k-th `tm.recv` row of that run, in
`idx` order. The join key is therefore the ARRIVAL ORDINAL, and it is verifiable
independently of this reasoning: the two rows are written inside one call, so
they must share a simulation time. Over the accepted 1200-run corpus that holds
for all 9812 alarms with zero exceptions.

CONSERVATION
------------
Every raw `rnd.alarm` row receives exactly ONE terminal disposition. The
dispositions partition the raw rows exactly — `total == matched + Σ unmatched` —
and the equation is carried in the scored output rather than asserted here, so a
silent drop becomes a visible arithmetic failure. "No row was dropped" is a
claim; the conservation equation is the evidence.
"""

from __future__ import annotations

PRODUCER = {
    "category": "rnd.alarm",
    "emitted_by": "lifesat::RandomDetector::observe",
    "emitting_source": "src/RandomDetector.cc",
    "fields": {
        "n": "1-based ordinal of the telemetry observation on which this alarm "
             "fired; the value of RandomDetector::observations after its "
             "pre-increment",
    },
    "one_row_per": "alarm, not per observation",
}

CONSUMER = {
    "category": "tm.recv",
    "emitted_by": "lifesat::GroundStation::handleTelemetry",
    "emitting_source": "src/GroundStation.cc",
    "fields": {
        "ageS": "arrival age; PROVENANCE ONLY",
        "mode": "spacecraft mode; PROVENANCE ONLY",
        "rej": "rejected command count; PROVENANCE ONLY",
        "seq": "satellite telemetry sequence number; PROVENANCE ONLY — it is "
               "assigned on the spacecraft and skips on in-flight loss, so it "
               "is NEVER a join key for an arrival-ordered quantity",
        "vbat": "battery voltage; PROVENANCE ONLY",
    },
    "unit": "received_telemetry_observation",
}

JOIN = {
    "consumer_key": "1-based position of the tm.recv row within the run, in "
                    "idx order",
    "join_key_id": "random_alarm_arrival_ordinal",
    "producer_key": "rnd.alarm field 'n'",
    "structural_witness": (
        "tm.recv is logged and observe() is called inside a single "
        "GroundStation::handleTelemetry invocation, so a correctly joined pair "
        "shares a simulation time exactly. Time equality is recorded per match "
        "and is not assumed."),
    "why_not_seq": (
        "seq is a spacecraft-assigned sequence number, not an arrival ordinal. "
        "Recounted from the raw CSV of the accepted corpus, seq equals n for "
        "not one alarm."),
}

# Terminal dispositions. Every raw rnd.alarm row gets exactly one.
DISPOSITIONS = (
    "matched",
    "unmatched_missing_ordinal_field",
    "unmatched_malformed_ordinal",
    "unmatched_ordinal_out_of_range",
    "unmatched_duplicate_ordinal",
)


class Binding:
    """The result of binding one run's alarms to its observations."""

    def __init__(self, observations, rows):
        self.observation_count = len(observations)
        self.rows = rows
        self.alarmed_ordinals = {r["ordinal"] for r in rows
                                 if r["disposition"] == "matched"}

    @property
    def conservation(self):
        """total == matched + Σ unmatched, stated as arithmetic, not as a claim."""
        counts = {name: 0 for name in DISPOSITIONS}
        for row in self.rows:
            counts[row["disposition"]] += 1
        matched = counts["matched"]
        unmatched = sum(value for name, value in counts.items()
                        if name != "matched")
        total = len(self.rows)
        inconsistent = sum(1 for r in self.rows
                           if r["disposition"] == "matched"
                           and not r["time_consistent"])
        return {
            "by_disposition": counts,
            "exact": total == matched + unmatched,
            "join_key_id": JOIN["join_key_id"],
            "matched": matched,
            "matched_time_inconsistent": inconsistent,
            "observation_count": self.observation_count,
            "raw_alarm_rows": total,
            "unmatched": unmatched,
        }


def bind(events):
    """Bind every rnd.alarm row of one run to its observation, or type why not.

    Never raises on bad data and never drops a row: a row that cannot be joined
    is carried with the reason it could not be, because a dropped row is exactly
    the failure mode this module exists to make impossible.
    """
    observations = [row for row in events if row["cat"] == "tm.recv"]
    times = [row["t"] for row in observations]

    rows, seen = [], {}
    for event in events:
        if event["cat"] != "rnd.alarm":
            continue
        record = {"disposition": None, "ordinal": None, "raw": event["f"].get("n"),
                  "time": event["t"], "time_consistent": None}
        raw = event["f"].get("n")
        if raw is None:
            record["disposition"] = "unmatched_missing_ordinal_field"
        else:
            try:
                ordinal = int(raw)
            except (TypeError, ValueError):
                record["disposition"] = "unmatched_malformed_ordinal"
            else:
                record["ordinal"] = ordinal
                if not 1 <= ordinal <= len(observations):
                    record["disposition"] = "unmatched_ordinal_out_of_range"
                elif ordinal in seen:
                    record["disposition"] = "unmatched_duplicate_ordinal"
                else:
                    seen[ordinal] = True
                    record["disposition"] = "matched"
                    record["time_consistent"] = \
                        abs(times[ordinal - 1] - event["t"]) < 1e-9
        rows.append(record)
    return Binding(observations, rows)

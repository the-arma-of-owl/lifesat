#!/usr/bin/env python3
"""Task-4 regression: the F4 rejection counter must be VERIFIED, not merely read.

Contract: f4_semantics (authority: "each rejection increments the onboard
rejected-command counter by exactly 1"), edge cases `counter increments by more
than one between observations`, `skipped counter values`, `several rejections
before the first eligible observation`, and outcome `unresolved`.

Defect this pins: an eligible observation carrying ANY d3 alarm was scored
`reported` even when the counter had not moved, so an unexplained alarm could
manufacture a reporting success.

These tests target the PRODUCTION scorer only. reference_scorer.py is a frozen
Task-3 asset and is deliberately not modified to satisfy them.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.dirname(HERE)
for p in (HERE, ANALYSIS):
    if p not in sys.path:
        sys.path.insert(0, p)

from scoring import families  # noqa: E402

REJECTION_T = 1000.0


def observation(seq, recv, rej, age=0.02, idx=None):
    """A tm.recv row; source time is recv - age."""
    fields = {"seq": str(seq), "ageS": str(age)}
    if rej is not None:
        fields["rej"] = str(rej)
    return {"idx": idx if idx is not None else int(seq), "t": recv,
            "cat": "tm.recv", "f": fields}


def alarm(seq, t, channel="security", idx=None):
    return {"idx": idx if idx is not None else 9000 + int(seq), "t": t,
            "cat": "d3.alarm", "f": {"tmSeq": str(seq), "channel": channel}}


def rejection(t=REJECTION_T, cmd_id="1"):
    return {"action_id": "fixture#truth:%s" % cmd_id, "wire_id": cmd_id,
            "action": "replay", "delivered": True, "outcome": "rejected",
            "outcome_t": t, "outcome_row": int(cmd_id), "t": t - 0.03}


class TestF4CounterVerification(unittest.TestCase):
    """Each case is a constructed run: a baseline observation, then the
    observation that is (or is not) eligible for the rejection(s)."""

    def _score(self, events, rejections):
        return families.secondary_reporting(events, rejections)

    def test_1_increment_of_one_with_alarm_is_reported(self):
        events = [observation(10, 900.0, rej=0),
                  observation(11, 1100.0, rej=1),
                  alarm(11, 1100.0)]
        block, reporting = self._score(events, [rejection()])
        self.assertEqual(
            (block["reported"], block["not_reported"], block["unresolved"]),
            (1, 0, 0),
            "a +1 increment confirmed on an alarming observation is reported; got %r"
            % {k: block[k] for k in ("reported", "not_reported", "unresolved")})
        self.assertEqual(block["denominator"], 1)
        self.assertIn("11", reporting,
                      "a verified observation belongs to the F4 reporting set")

    def test_2_increment_of_one_without_alarm_is_not_reported(self):
        events = [observation(10, 900.0, rej=0),
                  observation(11, 1100.0, rej=1)]
        block, reporting = self._score(events, [rejection()])
        self.assertEqual(
            (block["reported"], block["not_reported"], block["unresolved"]),
            (0, 1, 0),
            "a confirmed increment with no alarm is not_reported; got %r"
            % {k: block[k] for k in ("reported", "not_reported", "unresolved")})
        self.assertEqual(block["denominator"], 1,
                         "not_reported stays in the denominator")
        self.assertIn("11", reporting,
                      "the increment was verified, so the observation is still an "
                      "F4 reporting opportunity and must leave the F3 denominator")

    def test_3_unchanged_counter_with_alarm_is_unresolved_never_reported(self):
        """The defect: an unexplained alarm must not manufacture a report."""
        events = [observation(10, 900.0, rej=7),
                  observation(11, 1100.0, rej=7),
                  alarm(11, 1100.0)]
        block, reporting = self._score(events, [rejection()])
        self.assertEqual(
            block["reported"], 0,
            "an alarm on an observation whose counter did not move MUST NOT be "
            "scored reported; got reported=%d" % block["reported"])
        self.assertEqual(
            block["unresolved"], 1,
            "the evidence chain is broken, so the event is unresolved; got %r"
            % {k: block[k] for k in ("reported", "not_reported", "unresolved")})
        self.assertEqual(block["denominator"], 0,
                         "an unresolved event enters neither numerator nor "
                         "denominator")
        self.assertNotIn("11", reporting,
                         "an unverified observation must stay in the F3 "
                         "direct-detection denominator")

    def test_4_two_rejections_one_observation_increment_two_both_reported(self):
        events = [observation(10, 900.0, rej=0),
                  observation(11, 1100.0, rej=2),
                  alarm(11, 1100.0)]
        rejections = [rejection(1000.0, "1"), rejection(1000.5, "2")]
        block, reporting = self._score(events, rejections)
        self.assertEqual(
            (block["reported"], block["not_reported"], block["unresolved"]),
            (2, 0, 0),
            "two rejections coalescing into one +2 observation report BOTH; got %r"
            % {k: block[k] for k in ("reported", "not_reported", "unresolved")})
        self.assertEqual(block["denominator"], 2,
                         "the shared observation is one unit, but the two evidence "
                         "events are counted separately")
        self.assertIn("11", reporting)

    def test_5_two_rejections_but_only_one_increment_is_fail_closed(self):
        events = [observation(10, 900.0, rej=0),
                  observation(11, 1100.0, rej=1),
                  alarm(11, 1100.0)]
        rejections = [rejection(1000.0, "1"), rejection(1000.5, "2")]
        block, reporting = self._score(events, rejections)
        self.assertEqual(
            block["reported"], 0,
            "a +1 increment cannot account for two rejections; nothing may be "
            "reported. got reported=%d" % block["reported"])
        self.assertEqual(
            block["unresolved"], 2,
            "both evidence events are unresolved (fail-closed); got %r"
            % {k: block[k] for k in ("reported", "not_reported", "unresolved")})
        self.assertEqual(block["denominator"], 0)
        self.assertNotIn("11", reporting)

    # -- supporting fail-closed cases ---------------------------------------
    def test_6_missing_counter_field_is_unresolved(self):
        events = [observation(10, 900.0, rej=0),
                  observation(11, 1100.0, rej=None),
                  alarm(11, 1100.0)]
        block, _ = self._score(events, [rejection()])
        self.assertEqual((block["reported"], block["unresolved"]), (0, 1),
                         "a missing `rej` field cannot verify the chain")

    def test_7_malformed_counter_is_unresolved(self):
        events = [observation(10, 900.0, rej=0),
                  {"idx": 11, "t": 1100.0, "cat": "tm.recv",
                   "f": {"seq": "11", "ageS": "0.02", "rej": "not-a-number"}},
                  alarm(11, 1100.0)]
        block, _ = self._score(events, [rejection()])
        self.assertEqual((block["reported"], block["unresolved"]), (0, 1),
                         "a malformed `rej` value cannot verify the chain")

    def test_8_decreasing_counter_is_unresolved(self):
        events = [observation(10, 900.0, rej=5),
                  observation(11, 1100.0, rej=3),
                  alarm(11, 1100.0)]
        block, _ = self._score(events, [rejection()])
        self.assertEqual((block["reported"], block["unresolved"]), (0, 1),
                         "a decreasing counter (reset or tamper) breaks the chain")

    def test_9_no_eligible_observation_is_no_reporting_opportunity(self):
        events = [observation(10, 900.0, rej=0)]
        block, reporting = self._score(events, [rejection()])
        self.assertEqual(
            (block["reported"], block["not_reported"], block["unresolved"],
             block["no_reporting_opportunity"]), (0, 0, 0, 1),
            "a rejection with no later eligible observation is censored")
        self.assertEqual(reporting, set())

    def test_10_inflight_observation_is_not_eligible(self):
        """Source time, not arrival order, decides eligibility."""
        events = [observation(10, 900.0, rej=0),
                  observation(11, 1000.005, rej=0, age=0.02),   # sampled at 999.985
                  observation(12, 1100.0, rej=1),
                  alarm(12, 1100.0)]
        block, reporting = self._score(events, [rejection()])
        self.assertEqual(
            (block["reported"], block["unresolved"]), (1, 0),
            "the in-flight observation (source time 999.985 < 1000.0) is skipped "
            "and the next observation carries the increment")
        self.assertIn("12", reporting)
        self.assertNotIn("11", reporting)

    # -- broken-chain cases: a mismatch must never re-anchor the expectation --
    def test_12_broken_chain_does_not_re_anchor(self):
        """baseline=0 -> rej1 -> obs rej=0/alarm -> rej2 -> obs rej=1/alarm.

        The first observation stalls (expected absolute 1, observed 0). Under a
        RELATIVE baseline the second observation would look like a clean +1 and
        report; under the absolute rule its expectation is 2, so it is unresolved
        too. Nothing is reported and the denominator stays empty.
        """
        events = [observation(10, 900.0, rej=0),          # anchor, before rej1
                  observation(11, 1100.0, rej=0),          # stalled
                  alarm(11, 1100.0),
                  observation(12, 1300.0, rej=1),          # would be +1 relatively
                  alarm(12, 1300.0)]
        rejections = [rejection(1000.0, "1"), rejection(1200.0, "2")]
        block, reporting = self._score(events, rejections)
        self.assertEqual(
            (block["reported"], block["not_reported"], block["unresolved"],
             block["denominator"]), (0, 0, 2, 0),
            "a broken chain must not re-anchor: expected reported=0, "
            "unresolved=2, denominator=0; got %r"
            % {k: block[k] for k in ("reported", "not_reported", "unresolved",
                                     "denominator")})
        self.assertEqual(
            reporting, set(),
            "neither observation was verified, so neither may be removed from "
            "the F3 direct-detection denominator")

    def test_13_catch_up_observation_is_classified_by_its_own_first_eligible(self):
        """baseline=0 -> rej1 -> obs rej=0 -> rej2 -> obs rej=2/alarm.

        Contract first-eligible rule: each evidence event is decided at ITS OWN
        first source-time eligible observation.

          rej1 -> obs seq=11, expected absolute 0+1 = 1, observed 0 -> unresolved
          rej2 -> obs seq=12, expected absolute 0+2 = 2, observed 2 -> verified,
                  and the alarm on that callback makes it reported

        The catch-up therefore rehabilitates only the SECOND event. The first
        stays unresolved: a later observation can never convert an already
        unresolved evidence event into reported.
        """
        events = [observation(10, 900.0, rej=0),
                  observation(11, 1100.0, rej=0),
                  observation(12, 1300.0, rej=2),
                  alarm(12, 1300.0)]
        rejections = [rejection(1000.0, "1"), rejection(1200.0, "2")]
        block, reporting = self._score(events, rejections)
        self.assertEqual(
            (block["reported"], block["not_reported"], block["unresolved"],
             block["denominator"]), (1, 0, 1, 1),
            "the catch-up observation verifies only its own event: expected "
            "reported=1, unresolved=1, denominator=1; got %r"
            % {k: block[k] for k in ("reported", "not_reported", "unresolved",
                                     "denominator")})
        self.assertIn("12", reporting, "the catch-up observation was verified")
        self.assertNotIn("11", reporting,
                         "the stalled observation was never verified")

    def test_14_unresolved_event_is_never_converted_later(self):
        """A later verified observation does not rescue an earlier failure."""
        events = [observation(10, 900.0, rej=0),
                  observation(11, 1100.0, rej=0),          # rej1 stalls here
                  observation(12, 1300.0, rej=1),          # rej1's absolute value
                  alarm(12, 1300.0)]
        block, _ = self._score(events, [rejection(1000.0, "1")])
        self.assertEqual(
            (block["reported"], block["unresolved"]), (0, 1),
            "the evidence event is decided at its FIRST eligible observation and "
            "stays unresolved; a later observation carrying the right absolute "
            "value must not convert it. got %r"
            % {k: block[k] for k in ("reported", "not_reported", "unresolved")})

    def test_15_no_anchorable_baseline_is_unresolved(self):
        """Without a verifiable counter before the first rejection, fail closed."""
        events = [observation(11, 1100.0, rej=1), alarm(11, 1100.0)]
        block, reporting = self._score(events, [rejection(1000.0, "1")])
        self.assertEqual(
            (block["reported"], block["unresolved"]), (0, 1),
            "no observation precedes the first rejection, so the absolute "
            "expectation cannot be anchored and nothing may be reported")
        self.assertEqual(reporting, set())

    def test_11_counter_verification_is_declared_in_the_output(self):
        events = [observation(10, 900.0, rej=0), observation(11, 1100.0, rej=1),
                  alarm(11, 1100.0)]
        block, _ = self._score(events, [rejection()])
        self.assertEqual(block["counter_verification"],
                         "absolute_expected_counter_anchored_once",
                         "the output must declare that the counter is verified")


if __name__ == "__main__":
    unittest.main(verbosity=2)

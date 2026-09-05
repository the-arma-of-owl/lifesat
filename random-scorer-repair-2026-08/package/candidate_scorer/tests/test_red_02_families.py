#!/usr/bin/env python3
"""RED-2 / RED-7: F0 execution, F1 prevention and F2 state transition must be
separate, and family isolation must hold.

Contract: ISS-02, ISS-21, ISS-22, INV-05, INV-12, INV-24, INV-28;
fixtures FX-F0-F2-SEPARATION, FX-A3-IDEMPOTENT-ACCEPT.
"""
import os
import unittest
from collections import Counter

from red_common import RedTest, O, MISSING

FIXTURE = "A3-D1-s00-r0"


class TestFamilySeparation(RedTest):

    MISSING_ = MISSING

    def setUp(self):
        self.ep = os.path.join(O.RESULTS, FIXTURE + "-events.csv")
        self.tp = os.path.join(O.RESULTS, FIXTURE + "-truth.csv")
        self.events = O.load_events(self.ep)
        self.truth = O.load_truth(self.tp)
        self.matched = O.match_actions_to_outcomes(FIXTURE, self.events, self.truth, "A3")

    def test_prevention_is_not_a_state_effect(self):
        """INV-05/INV-24: a rejected command changes no state."""
        rejected = [m for m in self.matched if m["outcome"] == "reject"]
        accepted = [m for m in self.matched if m["outcome"] == "accept"]
        self.assertGreater(len(rejected), 0, "fixture precondition: D1 rejects replays")
        verdict = O.classify_accepted(FIXTURE, self.events, self.matched)
        transitions = sum(1 for v in verdict.values() if v == "state_changed")

        out = self.target_run(FIXTURE)
        expected = ("F1.numerator = %d prevention(s) and F2.state_changed = %d, with "
                    "%d effect event(s): a prevented attack changes no state"
                    % (len(rejected), transitions, transitions))
        why = ("score.py:126-130 creates an effect interval for every hostile "
               "tc.reject, so a prevented attack is scored with post-compromise "
               "detection metrics and F1 becomes indistinguishable from F2")
        evidence = ("%s: %d reject(s), %d accept(s)"
                    % (FIXTURE, len(rejected), len(accepted)))

        self.assert_value(out, "F1.numerator", len(rejected), "INV-05/INV-24",
                          "prevention is not counted as its own family",
                          expected, why, evidence)
        self.assert_value(out, "F2.state_changed", transitions, "INV-05/INV-24",
                          "prevention materialised as a state effect",
                          expected, why, evidence)
        ee = self.assert_field(out, "effect_events", "INV-05/INV-24",
                               "no effect-event set in the output", expected, why,
                               evidence)
        self.assertEqual(
            len(ee), transitions,
            self.defect("INV-05/INV-24", "rejections generate effect events",
                        expected, "%d effect event(s)" % len(ee), why, evidence))

    def test_rejection_reporting_is_not_direct_detection(self):
        """INV-12: a rejection-counter transition is F4, never F3."""
        run = "A3-D3-s00-r0"
        ev = O.load_events(O.RESULTS + "/" + run + "-events.csv")
        tr = O.load_truth(O.RESULTS + "/" + run + "-truth.csv")
        chan = Counter(r["f"].get("channel") for r in ev if r["cat"] == "d3.alarm")
        self.assertGreater(chan["security"], 0,
                           "fixture precondition: security-channel alarms exist")

        out = self.target_run(run)
        expected = ("F3.D3 scored only on physical/logical divergence: with no "
                    "received tampered/delayed telemetry in an A3 run its TP+FN is 0, "
                    "and the %d security-channel alarm(s) are counted in family F4"
                    % chan["security"])
        why = ("score.py:126-130 builds the rejection-to-first-telemetry interval and "
               "scores it with the same detection metrics as a real compromise, so a "
               "D1+D3 ensemble result is published as twin behavioural detection")
        evidence = ("%s: %d security-channel and %d physical-channel d3 alarm(s)"
                    % (run, chan["security"], chan["physical"]))

        tp = self.assert_field(out, "F3.D3.tp", "INV-12",
                               "no native-unit F3 block in the output",
                               expected, why, evidence)
        fn = self.get_path(out, "F3.D3.fn", 0)
        self.assertEqual(
            tp + fn, 0,
            self.defect("INV-12", "secondary reporting scored as direct detection",
                        expected, "F3.D3 truth positives TP+FN = %d" % (tp + fn),
                        why, evidence))
        self.assert_value(out, "F4.numerator", chan["security"], "INV-12",
                          "rejection reporting missing from family F4",
                          expected, why, evidence)

    def test_a3_accepted_replays_split_330_84(self):
        """INV-28: idempotent acceptances execute but do not transition state."""
        oracle = Counter()
        for run, ev, tr in O.corpus("A3-D?-s??-r0-events.csv"):
            m = O.match_actions_to_outcomes(run, ev, tr, "A3")
            for v in O.classify_accepted(run, ev, m).values():
                oracle[v] += 1
            oracle["accepted"] += sum(1 for a in m if a["outcome"] == "accept")
        self.assertEqual(
            (oracle["accepted"], oracle["state_changed"],
             oracle["accepted_idempotent_no_change"]), (414, 330, 84),
            "oracle self-check: the A3 corpus must reproduce 414 = 330 + 84")

        # Read the split out of the TARGET's own output, summed over the corpus.
        got = Counter()
        for run, ev, tr in O.corpus("A3-D?-s??-r0-events.csv"):
            out = self.target_run(run)
            got["accepted"] += self.get_path(out, "F1.accepted", 0) or 0
            got["state_changed"] += self.get_path(out, "F2.state_changed", 0) or 0
            idem = self.get_path(out, "F2.accepted_idempotent_no_change", self.MISSING_)
            if idem is not self.MISSING_:
                got["accepted_idempotent_no_change"] += idem
            else:
                got["missing_field_runs"] += 1

        expected = ("F2.state_changed = 330 and "
                    "F2.accepted_idempotent_no_change = 84 across the 240 A3 runs, "
                    "with the 84 generating no effect event")
        why = ("an accepted command that rewrites the prevailing gain with the "
               "identical value alters nothing; counting it as a state transition "
               "inflates the F2 numerator and the miss denominator. The value law "
               "paramValue = 1.0 + 0.1*(cmdId mod 5) (GroundStation.cc:98) makes the "
               "prevailing value reconstructible offline, so there is no excuse for "
               "omitting the classification")
        self.assertEqual(
            got["missing_field_runs"], 0,
            self.defect("INV-28", "no idempotency classification in the output",
                        expected,
                        "F2.accepted_idempotent_no_change absent from %d of %d A3 run "
                        "outputs" % (got["missing_field_runs"], 240),
                        why, "oracle split: 414 = 330 + 84"))
        self.assertEqual(
            (got["state_changed"], got["accepted_idempotent_no_change"]), (330, 84),
            self.defect("INV-28", "idempotent acceptances counted as state transitions",
                        expected,
                        "state_changed = %d, accepted_idempotent_no_change = %d"
                        % (got["state_changed"], got["accepted_idempotent_no_change"]),
                        why, "%d accepted replays in total" % got["accepted"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""RED-5: every A4 action reconciles to exactly one disposition; drops never vanish.

Contract: ISS-04, ISS-13, INV-04, INV-09, INV-13; fixtures
FX-A4D2-CORPUS-CARDINALITY, FX-A4D2-EMPTY-WINDOW-S48.
"""
import unittest
from collections import Counter

from red_common import RedTest, O

FIXTURE = "A4-D3-s00-r0"


class TestA4Accounting(RedTest):

    def setUp(self):
        self.events = O.load_events(O.RESULTS + "/" + FIXTURE + "-events.csv")
        self.truth = O.load_truth(O.RESULTS + "/" + FIXTURE + "-truth.csv")

    def test_every_action_lands_in_exactly_one_disposition(self):
        """INV-04: the four dispositions sum to the action count."""
        disp, _per = O.a4_dispositions(self.events, self.truth)
        n_actions = sum(1 for r in self.truth
                        if r["f"].get("event") in ("tamper", "delay", "drop"))
        self.assertEqual(sum(disp.values()), n_actions,
                         "oracle self-check: dispositions partition the actions")

        out = self.target_run(FIXTURE)
        expected = ("action_accounting.total_actions = %d with dispositions %s "
                    "summing to that total" % (n_actions, dict(disp)))
        why = ("score.py builds point intervals only for tampered/delayed packets "
               "that were received, so drop actions are silently absent and the "
               "published rate describes received packets while being labelled A4")
        evidence = "%s: %s" % (FIXTURE, dict(disp))

        self.assert_value(out, "action_accounting.total_actions", n_actions,
                          "INV-04", "A4 actions do not reconcile to a partition",
                          expected, why, evidence)
        got = self.assert_field(out, "action_accounting.dispositions", "INV-04",
                                "no disposition partition in the output",
                                expected, why, evidence)
        self.assertEqual(
            sum(got.values()), n_actions,
            self.defect("INV-04", "dispositions do not sum to the action count",
                        expected, "dispositions %r summing to %d"
                        % (got, sum(got.values())), why, evidence))
        for k in ("received_modified", "received_delayed", "dropped", "unresolved"):
            self.assertEqual(
                got.get(k), disp.get(k, 0),
                self.defect("INV-04", "disposition `%s` mis-counted" % k,
                            expected, "%s = %r" % (k, got.get(k)), why, evidence))

    def test_drops_are_not_silently_removed_from_the_denominator(self):
        """INV-04: the corpus-level drop count must survive scoring."""
        oracle = Counter()
        for run, ev, tr in O.corpus("A4-D3-s??-r0-events.csv"):
            d, _ = O.a4_dispositions(ev, tr)
            oracle.update(d)
        self.assertEqual((oracle["received_modified"], oracle["received_delayed"],
                          oracle["dropped"]), (270, 230, 249),
                         "oracle self-check: 270 tamper + 230 delay + 249 drop")

        got = Counter()
        missing = 0
        for run, _ev, _tr in O.corpus("A4-D3-s??-r0-events.csv"):
            out = self.target_run(run)
            d = self.get_path(out, "action_accounting.dispositions")
            if not isinstance(d, dict):
                missing += 1
                continue
            got.update(d)

        expected = ("749 A4 action(s) in the cell denominator "
                    "(270 modified + 230 delayed + 249 dropped)")
        why = ("the published 8.4% figure is a received-observation rate presented "
               "as an all-A4 miss rate; the 249 drops are neither successes nor "
               "misses because they never enter the denominator")
        evidence = ("tm.send is fully logged, so the drop/benign-loss split is "
                    "derivable offline")

        self.assertEqual(
            missing, 0,
            self.defect("INV-04", "no action accounting in the output", expected,
                        "dispositions absent from %d of 60 run outputs" % missing,
                        why, evidence))
        self.assertEqual(
            (got["received_modified"], got["received_delayed"], got["dropped"]),
            (270, 230, 249),
            self.defect("INV-04", "249 dropped actions excluded from the denominator",
                        expected, "modified %d, delayed %d, dropped %d"
                        % (got["received_modified"], got["received_delayed"],
                           got["dropped"]), why, evidence))

    def test_drop_has_no_synthetic_receive_and_a_reported_opportunity_class(self):
        """INV-09: a drop has no receive time and its absence must be reported."""
        recv = {r["f"].get("seq") for r in self.events if r["cat"] == "tm.recv"}
        drops = [r["f"]["tmSeq"] for r in self.truth if r["f"].get("event") == "drop"]
        self.assertTrue(all(q not in recv for q in drops),
                        "fixture precondition: dropped packets never arrive")

        out = self.target_run(FIXTURE)
        expected = ("action_accounting.no_decision_opportunity present and equal to "
                    "the number of drops D3 could not decide on, with no drop bound "
                    "to a synthetic receive time")
        why = ("D3 decides only inside observeTelemetry, which a dropped packet never "
               "triggers; the absence of a decision must be shown, not hidden, or a "
               "reader cannot tell a missed drop from an unscoreable one")
        evidence = ("%s: %d drop(s), 0 D3 alarms attributable to them"
                    % (FIXTURE, len(drops)))

        self.assert_field(out, "action_accounting.no_decision_opportunity",
                          "INV-09", "drop detection has no reported opportunity class",
                          expected, why, evidence)
        # a drop must never appear as a scored effect event
        ee = self.get_path(out, "effect_events", [])
        if isinstance(ee, list):
            send = {r["f"].get("seq"): r["t"] for r in self.events
                    if r["cat"] == "tm.send"}
            for q in drops:
                s = send.get(q)
                if s is None:
                    continue
                self.assertFalse(
                    any(abs(e.get("start", -1) - s) < 1e-6 for e in ee),
                    self.defect("INV-09", "drop bound to a synthetic receive time",
                                expected,
                                "an effect event starts at the scheduled send time "
                                "%.4f of dropped tmSeq=%s" % (s, q), why, evidence))


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""RED-3: effect windows close on the next differing write, legitimate or hostile.

Contract: effect_event_definition.effect_window_closing_rule (single normative
source), INV-23, INV-28, INV-32; fixture FX-A3-EFFECT-WINDOW-CLOSE.
"""
import unittest

from red_common import RedTest, O

FIXTURE = "A3-D0-s00-r0"


class TestEffectWindow(RedTest):

    def setUp(self):
        self.events = O.load_events(O.RESULTS + "/" + FIXTURE + "-events.csv")
        self.truth = O.load_truth(O.RESULTS + "/" + FIXTURE + "-truth.csv")
        self.matched = O.match_actions_to_outcomes(FIXTURE, self.events,
                                                   self.truth, "A3")

    def test_precondition_closing_rule_is_the_single_normative_one(self):
        """The contract states the closing rule exactly once."""
        norm = self.contract["effect_event_definition"]["effect_window_closing_rule"]
        repeat = self.contract["idempotency_semantics"]["effect_window_rule"][
            "closes_normative"]
        self.assertEqual(norm, repeat,
                         "contract self-check: the closing rule must be stated once")
        self.assertIn("legitimate or hostile", norm)

    def test_window_closes_on_a_differing_write_of_either_origin(self):
        """INV-32: a later differing write closes the window, hostile or not."""
        windows = O.effect_windows(FIXTURE, self.events, self.matched)
        accepted = sum(1 for m in self.matched if m["outcome"] == "accept")

        out = self.target_run(FIXTURE)
        expected = ("%d effect event(s), each closing at the next accepted command - "
                    "legitimate OR hostile - that writes a different value to `gain`"
                    % len(windows))
        why = ("score.py:134-139 scans forward for the next acceptance whose cmdId is "
               "NOT in hostile_ids, so a later differing hostile write does not close "
               "the window and one corrupted state is counted as two")
        evidence = ("%s: %d accepted hostile command(s) yielding %d contract window(s)"
                    % (FIXTURE, accepted, len(windows)))

        ee = self.assert_field(out, "effect_events", "INV-32",
                               "no effect-event set in the output",
                               expected, why, evidence)
        self.assertEqual(
            len(ee), len(windows),
            self.defect("INV-32", "effect window closing rule", expected,
                        "%d effect event(s)" % len(ee), why, evidence))

        # every emitted window must end at a differing write or the run horizon
        stops = sorted(w["stop"] for w in windows)
        got_stops = sorted(e["stop"] for e in ee if "stop" in e)
        self.assertEqual(
            got_stops, stops,
            self.defect("INV-32", "window boundaries disagree with the closing rule",
                        "window stops %s" % ["%.3f" % x for x in stops[:4]],
                        "%s" % ["%.3f" % x for x in got_stops[:4]], why, evidence))

    def test_idempotent_write_neither_opens_nor_closes(self):
        """INV-28/INV-32: an identical rewrite is inert."""
        verdict = O.classify_accepted(FIXTURE, self.events, self.matched)
        idem = [i for i, v in verdict.items()
                if v == "accepted_idempotent_no_change"]
        windows = O.effect_windows(FIXTURE, self.events, self.matched)
        self.assertGreater(len(idem), 0,
                           "fixture precondition: this run has an idempotent acceptance")

        out = self.target_run(FIXTURE)
        expected = ("%d effect event(s): the %d idempotent acceptance(s) open none, "
                    "and F2.accepted_idempotent_no_change = %d"
                    % (len(windows), len(idem), len(idem)))
        why = ("an identical rewrite leaves the compromised value exactly as it was; "
               "opening a window for it double-counts one state, and closing one with "
               "it would end a compromise that is still in force")
        evidence = "%s: idempotent acceptance(s) at truth row(s) %s" % (
            FIXTURE, sorted(idem)[:5])

        self.assert_value(out, "F2.accepted_idempotent_no_change", len(idem),
                          "INV-28/INV-32",
                          "idempotent write not recognised", expected, why, evidence)
        ee = self.assert_field(out, "effect_events", "INV-28/INV-32",
                               "no effect-event set in the output",
                               expected, why, evidence)
        self.assertEqual(
            len(ee), len(windows),
            self.defect("INV-28/INV-32", "idempotent write opens a spurious window",
                        expected, "%d effect event(s)" % len(ee), why, evidence))

    def test_one_alarm_credits_at_most_one_effect_event(self):
        """INV-23: alarm attribution is one-to-one."""
        run = "A4-D3-s00-r0"
        ev = O.load_events(O.RESULTS + "/" + run + "-events.csv")
        tr = O.load_truth(O.RESULTS + "/" + run + "-truth.csv")
        alarms = [r for r in ev if r["cat"] == "d3.alarm"
                  and r["f"].get("channel") in ("physical", "logical")]

        out = self.target_run(run)
        expected = ("F3.D3.detectedEvents <= the number of attributable alarms (%d): "
                    "one alarm credits at most one effect event" % len(alarms))
        why = ("the pre-correction scorer credited up to three effect intervals to a "
               "single alarm, inflating event recall without any additional detection "
               "having occurred")
        evidence = "%s: %d physical/logical alarm(s)" % (run, len(alarms))

        detected = self.assert_field(out, "F3.D3.detectedEvents", "INV-23",
                                     "no native-unit event attribution in the output",
                                     expected, why, evidence)
        self.assertLessEqual(
            detected, len(alarms),
            self.defect("INV-23", "one alarm credited to several effect events",
                        expected, "detectedEvents = %d with %d alarm(s)"
                        % (detected, len(alarms)), why, evidence))


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""RED-4: one (run_identity, window_index) is exactly one D2 decision.

Contract: ISS-03, ISS-13, ISS-18, ISS-23, INV-03, INV-13, INV-21, INV-22, INV-29;
fixtures FX-A4D2-CORPUS-CARDINALITY, FX-D2-WINDOW-DEDUP-CORPUS,
FX-A4D2-EMPTY-WINDOW-S48, FX-D2-DELAY-WINDOW-S00-52468.
"""
import unittest
from collections import Counter

from red_common import RedTest, O

FIXTURE = "A4-D2-s00-r0"
EMPTY_WINDOW_RUN = "A4-D2-s48-r0"


class TestD2NativeUnit(RedTest):

    def test_one_decision_per_nonempty_window_not_per_observation(self):
        """INV-03: the D2 denominator is the window, not the telemetry row."""
        ev = O.load_events(O.RESULTS + "/" + FIXTURE + "-events.csv")
        nonempty, _alarms = O.d2_decision_units(ev)
        observations = sum(1 for r in ev if r["cat"] == "tm.recv")

        out = self.target_run(FIXTURE)
        expected = ("F3.D2 scored on %d non-empty 60 s window(s), with "
                    "evaluation_unit = 'flow_window_60s'" % len(nonempty))
        why = ("FlowDetector::closeWindow emits at most one decision per non-empty "
               "window; evaluating that single decision against every observation "
               "inside the window inflates TN and FN and dilutes FPR")
        evidence = ("%s: %d non-empty window(s) vs %d observation(s)"
                    % (FIXTURE, len(nonempty), observations))

        unit = self.assert_field(out, "F3.D2.evaluation_unit", "INV-03",
                                 "D2 has no declared native unit", expected, why,
                                 evidence)
        self.assertEqual(
            unit, "flow_window_60s",
            self.defect("INV-03", "D2 scored outside its native unit", expected,
                        "evaluation_unit = %r" % unit, why, evidence))
        d2 = self.get_path(out, "F3.D2", {})
        scored = sum(d2.get(k, 0) for k in ("tp", "fp", "fn", "tn"))
        self.assertEqual(
            scored, len(nonempty),
            self.defect("INV-03", "D2 decision replicated across observations",
                        expected, "%d scored unit(s) (observations: %d)"
                        % (scored, observations), why, evidence))

    def test_corpus_mapping_dedup_585_to_469(self):
        """INV-29: many action-window mappings collapse to one decision unit."""
        mappings = 0
        unique = set()
        for run, ev, tr in O.corpus("A4-D2-s??-r0-events.csv"):
            m, _u = O.a4_window_mappings(ev, tr)
            mappings += len(m)
            for _kind, w, _idx in m:
                unique.add((run, w))
        self.assertEqual((mappings, len(unique)), (585, 469),
                         "oracle self-check: 585 mappings -> 469 unique windows")
        cc = self.contract["window_semantics"]["decision_unit_dedup_rule"][
            "corpus_evidence"]
        self.assertEqual((cc["action_window_mappings"],
                          cc["unique_truth_positive_windows"]), (585, 469),
                         "contract self-check")

        got_maps = 0
        got_unique = 0
        missing = 0
        for run, _ev, _tr in O.corpus("A4-D2-s??-r0-events.csv"):
            out = self.target_run(run)
            d2 = self.get_path(out, "F3.D2", {})
            if "action_window_mappings" not in d2 or \
                    "unique_truth_positive_windows" not in d2:
                missing += 1
                continue
            got_maps += d2["action_window_mappings"]
            got_unique += d2["unique_truth_positive_windows"]

        expected = ("F3.D2.action_window_mappings summing to 585 and "
                    "F3.D2.unique_truth_positive_windows summing to 469 across the "
                    "60 A4-D2 runs")
        why = ("several A4 consequences can land in one 60 s window; scoring one "
               "decision per mapping would replicate a single D2 decision and inflate "
               "both numerator and denominator")
        evidence = "116 of the 585 mappings share a window with another mapping"

        self.assertEqual(
            missing, 0,
            self.defect("INV-29", "no deduplicated window decision unit exists",
                        expected, "mapping/dedup fields absent from %d of 60 run "
                        "outputs" % missing, why, evidence))
        self.assertEqual(
            (got_maps, got_unique), (585, 469),
            self.defect("INV-29", "window dedup figures do not match", expected,
                        "mappings %d -> unique %d" % (got_maps, got_unique), why,
                        evidence))

    def test_empty_expected_window_drop_is_no_decision_opportunity(self):
        """INV-13: a drop in an empty expected window is neither TP nor FN."""
        classes = Counter()
        for run, ev, tr in O.corpus("A4-D2-s??-r0-events.csv"):
            classes.update(O.a4_drop_opportunity_classes(ev, tr))
        self.assertEqual((classes["native_decision_opportunity"],
                          classes["no_native_decision_opportunity"]), (248, 1),
                         "oracle self-check: 249 drops = 248 + 1")

        out = self.target_run(EMPTY_WINDOW_RUN)
        expected = ("action_accounting.drop_opportunity_classes reporting the drop "
                    "with no native decision opportunity separately; corpus split "
                    "248 / 1")
        why = ("a drop whose expected-arrival window contains no telemetry produces "
               "no FlowDetector decision, so it can be neither a true positive nor a "
               "false negative and must be reported rather than silently absorbed")
        evidence = ("%s: drop truth row idx=21 at t=219410.019, expected-arrival "
                    "window 3657 = (219360, 219420] contains 0 tm.recv rows"
                    % EMPTY_WINDOW_RUN)

        got = self.assert_field(out, "action_accounting.drop_opportunity_classes",
                                "INV-13", "drop opportunity classes are not reported",
                                expected, why, evidence)
        self.assertEqual(
            got.get("no_native_decision_opportunity", 0), 1,
            self.defect("INV-13", "empty-window drop not classified", expected,
                        "drop_opportunity_classes = %r" % (got,), why, evidence))

    def test_window_index_agrees_with_the_interval_at_boundaries(self):
        """INV-21: ceil indexing matches the half-open-left interval."""
        for t, k in ((0.0, 1), (60.0, 1), (60.000001, 2), (120.0, 2), (119.999, 2)):
            self.assertEqual(O.observation_window(t), k,
                             "oracle self-check: t=%.6f -> window %d" % (t, k))
        on_boundary = 0
        for run, ev, tr in O.corpus("A4-D2-s??-r0-events.csv"):
            for r in ev:
                if r["cat"] == "tm.recv" and abs(r["t"] / 60 - round(r["t"] / 60)) < 1e-12:
                    on_boundary += 1
        self.assertEqual(on_boundary, 0,
                         "fail-closed precondition: no tm.recv on an exact boundary "
                         "(found %d)" % on_boundary)

        out = self.target_run(FIXTURE)
        expected = ("F3.D2.reporting_grace_s = 0.0: a D2 alarm is attributable when "
                    "its producing window overlaps the effect, with no additive term")
        why = ("the 60 s grace is a workaround for the missing window unit; with "
               "native-unit scoring it silently widens attribution and can credit an "
               "alarm to an effect in a different window")
        evidence = "score.py:52 REPORTING_GRACE = {'D3': 0.0, 'D2': 60.0, 'RND': 0.0}"

        self.assert_value(out, "F3.D2.reporting_grace_s", 0.0, "INV-21/INV-03",
                          "asymmetric reporting grace substitutes for the window",
                          expected, why, evidence)

    def test_expected_and_eventual_delay_windows_stay_distinct(self):
        """INV-22: the two windows of a delayed packet are different units."""
        ev = O.load_events(O.RESULTS + "/" + FIXTURE + "-events.csv")
        tr = O.load_truth(O.RESULTS + "/" + FIXTURE + "-truth.csv")
        send = {r["f"].get("seq"): r["t"] for r in ev if r["cat"] == "tm.send"}
        recv = {r["f"].get("seq"): r["t"] for r in ev if r["cat"] == "tm.recv"}
        we = O.expected_arrival_window(send["52468"])
        wa = O.observation_window(recv["52468"])
        self.assertEqual((we, wa), (8745, 8746),
                         "fixture self-check: expected 8745, eventual 8746")
        mappings, _ = O.a4_window_mappings(ev, tr)
        kinds = Counter(k for k, _w, _i in mappings)

        out = self.target_run(FIXTURE)
        expected = ("F3.D2.action_window_mappings counting the expected-arrival and "
                    "the eventual-receive window of a delayed packet as two distinct "
                    "units (this run: %d delay-expected + %d delay-eventual + %d "
                    "drop-expected = %d)"
                    % (kinds["delay_expected"], kinds["delay_eventual"],
                       kinds["drop_expected"], len(mappings)))
        why = ("the withheld packet perturbs the flow in the window where it should "
               "have arrived AND in the window where it eventually did; merging them "
               "hides one of the two and misattributes the alarm")
        evidence = ("%s tmSeq=52468: send %.1f -> expected window %d; receive %.4f -> "
                    "eventual window %d" % (FIXTURE, send["52468"], we,
                                            recv["52468"], wa))

        self.assert_value(out, "F3.D2.action_window_mappings", len(mappings),
                          "INV-22", "delayed packet collapsed to one unit",
                          expected, why, evidence)


if __name__ == "__main__":
    unittest.main(verbosity=2)

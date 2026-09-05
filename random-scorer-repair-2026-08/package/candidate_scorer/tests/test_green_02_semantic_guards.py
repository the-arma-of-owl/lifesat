#!/usr/bin/env python3
"""Task-5 semantic guards: unit tests for scorer behaviour the corpus fixtures
cannot exercise.

The Task-5 mutation suite found three mutations that the corpus-driven tests let
through, because the recorded runs never contain the situation involved:

  * no A3 run has a LATER hostile acceptance writing a DIFFERENT value, so the
    "closes on a differing write of either origin" rule is never stressed;
  * A4 effect events are single points, so an alarm can never overlap two of
    them and one-alarm-one-event is never stressed;
  * the cells used by the frozen tests happen to have equal macro and pooled
    values, so merging the two fields is invisible.

These are direct unit tests of the production symbols, with constructed inputs.
They never touch the frozen Task-3 assets or the Task-4 regression module.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.dirname(HERE)
for p in (HERE, ANALYSIS):
    if p not in sys.path:
        sys.path.insert(0, p)

from scoring import output, state  # noqa: E402


def accept(idx, t, cmd_id):
    return {"idx": idx, "t": t, "cat": "tc.accept",
            "f": {"cmdId": str(cmd_id), "seq": str(cmd_id), "type": "1"}}


class TestEffectWindowClosingOrigin(unittest.TestCase):
    """state.effect_windows: the closing write may be legitimate OR hostile."""

    def test_later_hostile_write_with_a_different_value_closes_the_window(self):
        # cmdId 1 -> gain 1.1, cmdId 2 -> gain 1.2 (1.0 + 0.1*(id mod 5))
        events = [accept(1, 100.0, 1), accept(2, 200.0, 2)]
        verdicts = {1: state.STATE_CHANGED, 2: state.STATE_CHANGED}
        windows = state.effect_windows(events, verdicts, horizon=1000.0)
        self.assertEqual(len(windows), 2,
                         "both hostile acceptances changed state")
        self.assertEqual(
            windows[0]["stop"], 200.0,
            "the first window MUST close at the later HOSTILE write that puts a "
            "different value in the same key; got stop=%r. Closing only on a "
            "legitimate write would hold it open to the horizon and count one "
            "corrupted state as two." % windows[0]["stop"])
        self.assertEqual(windows[1]["stop"], 1000.0,
                         "the last window runs to the horizon")

    def test_later_hostile_write_of_the_same_value_does_not_close(self):
        # cmdId 1 and cmdId 6 both map to gain 1.1
        events = [accept(1, 100.0, 1), accept(2, 200.0, 6), accept(3, 300.0, 2)]
        verdicts = {1: state.STATE_CHANGED, 2: state.IDEMPOTENT,
                    3: state.STATE_CHANGED}
        windows = state.effect_windows(events, verdicts, horizon=1000.0)
        first = next(w for w in windows if w["source_row"] == 1)
        self.assertEqual(
            first["stop"], 300.0,
            "an identical rewrite at t=200 neither closes nor opens a window; the "
            "first window must run on to the differing write at t=300, got %r"
            % first["stop"])
        self.assertEqual([w["source_row"] for w in windows], [1, 3],
                         "the idempotent acceptance opens no window")


class TestOneAlarmOneEffectEvent(unittest.TestCase):
    """state.credit_alarms: an alarm may credit at most one effect event."""

    def test_single_alarm_overlapping_three_events_credits_one(self):
        events = [{"kind": "accepted_hostile_command_effect", "start": 0.0,
                   "stop": 100.0},
                  {"kind": "accepted_hostile_command_effect", "start": 10.0,
                   "stop": 100.0},
                  {"kind": "accepted_hostile_command_effect", "start": 20.0,
                   "stop": 100.0}]
        detected, claimed = state.credit_alarms([50.0], events)
        self.assertEqual(
            detected, 1,
            "one alarm overlapping three windows credits exactly ONE event; got "
            "%d. Crediting all three inflates event recall without any additional "
            "detection having occurred." % detected)
        self.assertEqual(claimed, {0}, "the earliest unclaimed event is credited")

    def test_two_alarms_credit_two_distinct_events(self):
        events = [{"kind": "x", "start": 0.0, "stop": 100.0},
                  {"kind": "x", "start": 0.0, "stop": 100.0},
                  {"kind": "x", "start": 0.0, "stop": 100.0}]
        detected, claimed = state.credit_alarms([10.0, 20.0], events)
        self.assertEqual(detected, 2)
        self.assertEqual(claimed, {0, 1},
                         "each alarm claims the earliest still-unclaimed event")

    def test_alarm_outside_every_window_credits_nothing(self):
        events = [{"kind": "x", "start": 0.0, "stop": 10.0}]
        detected, _ = state.credit_alarms([50.0], events)
        self.assertEqual(detected, 0)


class TestMacroAndPooledAreDistinctEstimands(unittest.TestCase):
    """output.estimand_result: macro over defined runs != pooled ratio."""

    def test_unequal_run_weights_give_different_macro_and_pooled(self):
        # run A: 1/1 = 1.0 ; run B: 1/9 ~ 0.111  -> macro 0.5556, pooled 0.2
        pairs = [(1, 1), (1, 9)]
        runs = ["cell-s00-r0", "cell-s01-r0"]
        res = output.estimand_result("EST-TEST", "F0_attack_execution",
                                     "attack_action", pairs, runs)
        macro = res["macro_mean_over_defined_runs"]
        pooled = res["pooled_ratio"]
        self.assertAlmostEqual(macro, (1.0 + 1.0 / 9) / 2, places=9)
        self.assertAlmostEqual(pooled, 2.0 / 10, places=9)
        self.assertNotEqual(
            macro, pooled,
            "the run-macro mean and the pooled ratio are DIFFERENT estimands and "
            "must not be emitted from one computation; got macro=%r pooled=%r"
            % (macro, pooled))
        self.assertEqual(res["defined_run_count"], 2)
        self.assertEqual(res["total_run_count"], 2)

    def test_undefined_run_is_excluded_from_macro_but_counted(self):
        pairs = [(1, 2), (0, 0)]        # second run has no denominator
        runs = ["cell-s00-r0", "cell-s01-r0"]
        res = output.estimand_result("EST-TEST", "F0_attack_execution",
                                     "attack_action", pairs, runs)
        self.assertEqual(res["macro_mean_over_defined_runs"], 0.5,
                         "the macro mean covers the DEFINED runs only")
        self.assertEqual(res["pooled_ratio"], 0.5)
        self.assertEqual((res["defined_run_count"], res["total_run_count"]), (1, 2),
                         "both counts are mandatory so the exclusion is visible")
        per_run = res.get("per_run")
        self.assertIsInstance(
            per_run, list,
            "per_run records are mandatory so the exclusion can be audited; got %r"
            % (per_run,))
        self.assertEqual(len(per_run), 2,
                         "one per_run record per declared run")
        self.assertIsNone(per_run[1]["value"])
        self.assertEqual(per_run[1]["undefined_reason_code"],
                         "denominator_zero_no_positives")

    def test_all_zero_cell_gets_observed_counts_and_no_interval(self):
        res = output.estimand_result("EST-TEST", "F0_attack_execution",
                                     "attack_action", [(0, 5), (0, 7)],
                                     ["cell-s00-r0", "cell-s01-r0"])
        self.assertIsNone(
            res["uncertainty"],
            "an all-zero cell reports observed counts, never a [0,0] interval; "
            "got %r" % (res["uncertainty"],))
        for field in ("observed_numerator", "observed_denominator",
                      "defined_run_count", "total_run_count"):
            self.assertIn(field, res,
                          "the zero-event policy requires `%s`" % field)
        self.assertEqual((res["observed_numerator"], res["observed_denominator"]),
                         (0, 12))


class TestUncertaintyPolicy(unittest.TestCase):
    """output.estimand_result / percentile_bootstrap: the contract CI policy."""

    PAIRS = [(1, 1), (1, 9), (3, 4), (0, 5)]
    RUNS = ["c-s00-r0", "c-s01-r0", "c-s02-r0", "c-s03-r0"]

    def _res(self):
        return output.estimand_result("EST-TEST", "F0_attack_execution",
                                      "attack_action", self.PAIRS, self.RUNS)

    def test_ci_unit_is_the_run_not_the_observation(self):
        """CONTRACT CI-UNIT: resampling_unit must be the seven-day run."""
        ci = self._res()["uncertainty"]
        self.assertIsNotNone(ci, "a non-all-zero cell publishes an interval")
        self.assertEqual(
            ci["resampling_unit"], "run",
            "CONTRACT CI-UNIT VIOLATION: the bootstrap resampling unit is the "
            "seven-day run / seed index. Resampling observations treats "
            "within-run events as independent, ignores the run-cluster structure "
            "and produces an interval that is far too narrow. got %r"
            % ci["resampling_unit"])

    def test_ci_parameters_are_the_contract_ones(self):
        ci = self._res()["uncertainty"]
        self.assertIsNotNone(ci, "a non-all-zero estimand publishes an interval")
        self.assertEqual(ci["method"], "two-sided 95% percentile bootstrap")
        self.assertEqual(ci["resamples"], 2000)
        self.assertEqual(ci["seed"], 12345)

    def test_ci_is_deterministic(self):
        a = self._res()["uncertainty"]
        b = self._res()["uncertainty"]
        self.assertEqual(a, b, "seed 12345 makes the interval reproducible")

    def test_ci_brackets_the_macro_mean(self):
        res = self._res()
        ci, macro = res["uncertainty"], res["macro_mean_over_defined_runs"]
        self.assertIsNotNone(ci, "a non-all-zero estimand publishes an interval")
        self.assertLessEqual(ci["ci_low"], macro)
        self.assertLessEqual(macro, ci["ci_high"])

    def test_ci_resamples_only_defined_runs(self):
        """An undefined run is excluded from the interval, as from the macro."""
        with_undefined = output.estimand_result(
            "EST-TEST", "F0_attack_execution", "attack_action",
            self.PAIRS + [(0, 0)], self.RUNS + ["c-s04-r0"])
        self.assertEqual(with_undefined["defined_run_count"], 4)
        self.assertEqual(with_undefined["total_run_count"], 5)
        self.assertEqual(
            with_undefined["uncertainty"], self._res()["uncertainty"],
            "adding a run with no denominator must not move the interval: the "
            "estimand is `over defined runs` and so is its bootstrap")

    def test_mixed_cell_zero_estimand_does_not_delete_the_other_interval(self):
        """CONTRACT CI-SCOPE: the zero-event rule is per ESTIMAND, not per cell.

        Estimand A is zero across all 60 runs; estimand B varies in the SAME
        scenario/defence cell. A must lose its interval; B must keep a full
        run-unit 2000-resample bootstrap. Suppressing B because A is zero would
        delete a legitimate interval and hide real seed-to-seed variability.
        """
        runs = ["A1-D3-s%02d-r0" % i for i in range(60)]
        zero_pairs = [(0, 8) for _ in runs]
        varying_pairs = [(i % 7, 8) for i in range(60)]

        a = output.estimand_result("EST-F2-01", "F2_state_transition",
                                   "attack_action", zero_pairs, runs)
        b = output.estimand_result("EST-F0-01", "F0_attack_execution",
                                   "attack_action", varying_pairs, runs)

        self.assertIsNone(
            a["uncertainty"],
            "the uniformly zero estimand publishes observed counts, not a [0,0] "
            "interval; got %r" % (a["uncertainty"],))
        self.assertEqual((a["observed_numerator"], a["observed_denominator"]),
                         (0, 480))
        self.assertEqual((a["defined_run_count"], a["total_run_count"]), (60, 60))

        self.assertIsNotNone(
            b["uncertainty"],
            "CONTRACT CI-SCOPE VIOLATION: estimand B varies across the 60 runs "
            "and MUST keep its interval. A sibling estimand being zero is not a "
            "reason to delete it.")
        ci = b["uncertainty"]
        self.assertEqual(ci["resampling_unit"], "run")
        self.assertEqual(ci["resamples"], 2000)
        self.assertEqual(ci["seed"], 12345)
        self.assertLess(ci["ci_low"], ci["ci_high"],
                        "a varying estimand yields a non-degenerate interval")
        self.assertEqual(b["defined_run_count"], 60)

    def test_zero_estimand_scope_is_independent_of_sibling_order(self):
        """The decision must not depend on which estimand is examined first."""
        runs = ["c-s%02d-r0" % i for i in range(60)]
        zero = output.estimand_result("EST-Z", "F2_state_transition",
                                      "attack_action", [(0, 4)] * 60, runs)
        vary = output.estimand_result("EST-V", "F0_attack_execution",
                                      "attack_action",
                                      [(i % 5, 4) for i in range(60)], runs)
        first_then_second = (zero["uncertainty"], vary["uncertainty"])
        vary2 = output.estimand_result("EST-V", "F0_attack_execution",
                                       "attack_action",
                                       [(i % 5, 4) for i in range(60)], runs)
        zero2 = output.estimand_result("EST-Z", "F2_state_transition",
                                       "attack_action", [(0, 4)] * 60, runs)
        self.assertEqual(first_then_second, (zero2["uncertainty"],
                                             vary2["uncertainty"]),
                         "each estimand is judged on its own defined runs, so "
                         "evaluation order cannot change the outcome")

    def test_pooled_ratio_carries_no_interval(self):
        res = self._res()
        self.assertIn("pooled_ratio", res)
        self.assertNotIn("pooled_uncertainty", res,
                         "a pooled ratio is descriptive only and gets no "
                         "inferential interval")


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""RED-8: run-macro-over-defined-runs and pooled ratio are separate named fields;
undefined values are null with a reason code, never 0.0.

Contract: ISS-07, ISS-08, ISS-20, INV-06, INV-07, INV-11, INV-17, INV-26.
"""
import unittest

from red_common import RedTest, O

BENIGN = "B0-D3-s00-r0"


class TestAggregationAndUndefined(RedTest):

    def test_undefined_ratios_are_not_coerced_to_zero(self):
        """INV-06: a zero denominator yields null plus a reason code."""
        out = self.target_run(BENIGN)
        tp = self.get_path(out, "F3.D3.tp", 0)
        fn = self.get_path(out, "F3.D3.fn", 0)
        fp = self.get_path(out, "F3.D3.fp", 0)
        self.assertEqual(
            tp + fn, 0,
            "fixture precondition: the benign baseline has no truth positives "
            "(target reported TP=%r FN=%r)" % (tp, fn))

        expected = ("F3.D3.recall = null with "
                    "recall_undefined_reason_code = denominator_zero_no_positives, "
                    "because TP+FN = 0")
        why = ("score.py:187 evaluates `tp/(tp+fn) if tp+fn else 0.0`; a 0.0 here is "
               "a factual claim about performance that the data cannot support and is "
               "indistinguishable from a detector that had positives and found none")
        evidence = "%s: TP=%d FP=%d FN=%d" % (BENIGN, tp, fp, fn)

        recall = self.get_path(out, "F3.D3.recall")
        self.assertIsNone(
            recall,
            self.defect("INV-06", "undefined recall coerced to 0.0", expected,
                        "recall = %r" % recall, why, evidence))
        self.assert_value(out, "F3.D3.recall_undefined_reason_code",
                          "denominator_zero_no_positives", "INV-06",
                          "undefined recall carries no reason code",
                          expected, why, evidence)

    def test_f05_uses_the_count_form_and_carries_its_qualifier(self):
        """INV-17: F0.5 = 1.25TP/(1.25TP + 0.25FN + FP) with a qualifier code."""
        sem = self.contract["score_semantics"]
        self.assertEqual(sem["f05_definition"]["normative_count_form"],
                         "F0.5 = 1.25*TP / (1.25*TP + 0.25*FN + FP)",
                         "contract self-check")
        row = next(x for x in sem["f05_truth_table"] if x["case"] == "TP=0, FP>0, FN=0")
        self.assertEqual(row["f05_code"], "false_alarm_only_no_truth_positives",
                         "contract self-check")

        expected = ("F3.D3 scored in its native unit, with f05 produced by the count "
                    "form and carrying defined_value_qualifier_code = %r"
                    % row["f05_code"])
        why = ("score.py:189-191 computes the component form with a 0.0 fallback, so "
               "the same 0.0 is emitted whether the detector missed real positives or "
               "there were none to miss; without the qualifier a reader cannot tell a "
               "false-alarm-only cell from a genuine failure")

        out = self.target_run(BENIGN)
        tp = self.assert_field(out, "F3.D3.tp", "INV-17",
                               "no native-unit F3 block to score F0.5 in",
                               expected, why)
        fp = self.get_path(out, "F3.D3.fp", 0)
        fn = self.get_path(out, "F3.D3.fn", 0)
        denom = 1.25 * tp + 0.25 * fn + fp
        evidence = ("%s: TP=%d FP=%d FN=%d, count denominator = %.2f"
                    % (BENIGN, tp, fp, fn, denom))
        self.assertGreater(
            denom, 0,
            self.defect("INV-17", "no scored decision content in the benign cell",
                        expected, "TP=%d FP=%d FN=%d" % (tp, fp, fn), why, evidence))
        want = 1.25 * tp / denom
        expected = ("F3.D3.f05 = %.6f from the count form, carrying "
                    "defined_value_qualifier_code = %r" % (want, row["f05_code"]))

        self.assertEqual(
            self.get_path(out, "F3.D3.f05"), want,
            self.defect("INV-17", "F0.5 not produced by the count form", expected,
                        "f05 = %r" % self.get_path(out, "F3.D3.f05"), why, evidence))
        self.assert_value(out, "F3.D3.defined_value_qualifier_code", row["f05_code"],
                          "INV-17", "F0.5 emitted without its qualifier code",
                          expected, why, evidence)

    def test_macro_and_pooled_are_separate_named_fields(self):
        """INV-07/INV-26: distinct names, with defined/total run counts."""
        expected = ("every estimand result carrying macro_mean_over_defined_runs, "
                    "pooled_ratio, defined_run_count and total_run_count as separate "
                    "named fields")
        why = ("the run-macro mean and the pooled ratio are different estimands "
               "(A3/D3: pooled 12.869% vs macro 16.125%); one label for both hides "
               "which denominator produced the number")
        evidence = "report.py:165-168 averages `1 - recallEvent` under `miss rate`"

        doc = self.corpus_or_fail("A3-D3-s??-r0-events.csv", "INV-07/INV-26",
                                  "macro and pooled estimands are not separated",
                                  expected, why, evidence)
        cells = self.assert_field(doc, "cells", "INV-07/INV-26",
                                  "no cell-level output", expected, why, evidence)
        self.assertTrue(cells, "cells must not be empty")
        results = cells[0].get("estimand_results", [])
        self.assertTrue(results, "a cell must carry estimand results")
        for field in ("macro_mean_over_defined_runs", "pooled_ratio",
                      "defined_run_count", "total_run_count"):
            self.assertIn(
                field, results[0],
                self.defect("INV-07/INV-26", "missing `%s`" % field, expected,
                            "estimand result keys: %s" % sorted(results[0].keys()),
                            why, evidence))
        self.assertEqual(
            results[0]["total_run_count"], 60,
            self.defect("INV-07/INV-26", "total_run_count does not cover the cell",
                        expected, "total_run_count = %r"
                        % results[0]["total_run_count"], why, evidence))

    def test_all_zero_cell_reports_counts_not_a_zero_interval(self):
        """INV-11: [0,0] is a bootstrap artefact, not an unseen-risk bound."""
        z = self.contract["uncertainty"]["zero_event_policy"]
        self.assertIn("MUST NOT be published", z["bootstrap_rule"],
                      "contract self-check")

        expected = ("the all-zero cell reported as observed counts "
                    "(numerator/denominator + defined_run_count/total_run_count) "
                    "with uncertainty = null, never as an interval")
        why = ("resampling 60 zeros returns zero in every replicate by construction; "
               "the interval carries no information about events never observed and "
               "reads as an upper bound on unseen risk")
        evidence = "A1/D3: 0 missed of 474 scored events across 60 runs"

        doc = self.corpus_or_fail("A1-D3-s??-r0-events.csv", "INV-11",
                                  "all-zero cell has no observed-count reporting",
                                  expected, why, evidence)
        results = doc["cells"][0]["estimand_results"]
        # Contract v1.4.2: "all-zero" is a property of ONE estimand result, so the
        # uniformly zero estimand must be selected by id rather than by position.
        res = next((r for r in results if r.get("estimand_id") == "EST-F2-01"), None)
        self.assertIsNotNone(
            res,
            self.defect("INV-11", "the all-zero estimand is absent from the cell",
                        expected, "estimand ids: %s"
                        % [r.get("estimand_id") for r in results], why, evidence))
        for field in ("numerator", "denominator", "defined_run_count",
                      "total_run_count", "uncertainty"):
            self.assertIn(
                field, res,
                self.defect("INV-11", "missing `%s`" % field, expected,
                            "estimand result keys: %s" % sorted(res.keys()),
                            why, evidence))
        self.assertIsNone(
            res["uncertainty"],
            self.defect("INV-11", "interval published for an all-zero estimand",
                        expected, "uncertainty = %r" % (res["uncertainty"],),
                        why, evidence))
        # ...and the zero estimand must NOT have suppressed its siblings.
        for sibling in results:
            if sibling.get("estimand_id") == "EST-F2-01":
                continue
            defined = [p["value"] for p in sibling.get("per_run", [])
                       if p["value"] is not None]
            if not defined or all(v == 0.0 for v in defined):
                continue
            self.assertIsNotNone(
                sibling["uncertainty"],
                self.defect("INV-11", "zero estimand suppressed a sibling interval",
                            "a varying estimand in the same cell keeps its "
                            "bootstrap interval",
                            "%s has uncertainty = None" % sibling["estimand_id"],
                            "the zero-event rule is scoped to one estimand result; "
                            "suppressing a sibling would delete real seed-to-seed "
                            "variability", evidence))


if __name__ == "__main__":
    unittest.main(verbosity=2)

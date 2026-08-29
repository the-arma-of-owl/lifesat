#!/usr/bin/env python3
"""Gates on the corrected result package.

These tests read a BUILT package and assert the properties Task 7 requires. They
do not rebuild it, so they can be run against any candidate output root:

    LIFESAT_PACKAGE=/path/to/results-v2-corrected \
        python3 -m unittest test_corrected_package_v1
"""
import hashlib
import json
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.dirname(HERE)
SIM = os.path.dirname(ANALYSIS)
sys.path.insert(0, ANALYSIS)

PKG = os.environ.get("LIFESAT_PACKAGE",
                     os.path.join(SIM, "results-v2-corrected"))
FILES = ("CORRECTED_RESULTS.json", "RUN_LEVEL_RESULTS.json",
         "POOLED_RESULTS.json", "INPUT_MANIFEST.json", "VALIDATION.json")


def load(name):
    with open(os.path.join(PKG, name), encoding="utf-8") as fh:
        return json.load(fh)


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


C = load("CORRECTED_RESULTS.json") if os.path.isdir(PKG) else None
R = load("RUN_LEVEL_RESULTS.json") if os.path.isdir(PKG) else None
P = load("POOLED_RESULTS.json") if os.path.isdir(PKG) else None
M = load("INPUT_MANIFEST.json") if os.path.isdir(PKG) else None
V = load("VALIDATION.json") if os.path.isdir(PKG) else None


@unittest.skipUnless(os.path.isdir(PKG), "package not built")
class Corpus(unittest.TestCase):
    def test_exactly_20_cells(self):
        self.assertEqual(len(C["cells"]), 20)
        self.assertEqual(len({c["cell"] for c in C["cells"]}), 20)

    def test_60_runs_per_cell(self):
        for cell in C["cells"]:
            self.assertEqual(cell["run_count"], 60, cell["cell"])

    def test_selected_corpus_is_exactly_1200(self):
        self.assertEqual(C["corpus"]["selected_runs"], 1200)
        self.assertEqual(len(M["runs"]), 1200)

    def test_180_rerun_plus_1020_raw(self):
        self.assertEqual(C["corpus"]["rerun_runs"], 180)
        self.assertEqual(C["corpus"]["raw_runs"], 1020)
        rerun = [r for r in M["runs"] if r["source"].endswith("results-v2-iss06")]
        self.assertEqual(len(rerun), 180)
        self.assertEqual({r["cell"] for r in rerun},
                         {"A1-D3", "A2-D3", "A3-D3"})

    def test_no_duplicate_missing_or_stray_run(self):
        ids = [r["identity"] for r in M["runs"]]
        self.assertEqual(len(ids), len(set(ids)))
        for cell in {r["cell"] for r in M["runs"]}:
            seeds = sorted(r["seed"] for r in M["runs"] if r["cell"] == cell)
            self.assertEqual(seeds, list(range(60)), cell)

    def test_input_hash_readback(self):
        for row in M["runs"][::37]:            # sampled: full sweep is in VALIDATION
            path = os.path.join(SIM, row["source"], row["identity"] + "-events.csv")
            self.assertEqual(sha256(path), row["events_sha256"], row["identity"])


@unittest.skipUnless(os.path.isdir(PKG), "package not built")
class Authority(unittest.TestCase):
    PINS = {"contract_json_sha256":
            "913848492f82502f5a28243534eaa3e2e19c3c023ebd8b49df8027b8ccf54e95",
            "seal_sha256":
            "5c575f3cee35000b4da45c63312ea166ed632b6a4efd7e3fc85efe707ea8d813",
            "scorer_sha256":
            "de16e29c73b7d2dcac87a114d755e130874eb892215be0947134afcf6f61a4cc",
            "old_raw_tree_sha256":
            "09893fc41cd5fab122b2d956bda46664d60d3b9f33aa68f95d4d41b408711c16",
            "rerun_tree_sha256":
            "f7e1d5fe90340d8bef2a0a512322d6b6017b39c56c1cec20a9531a0a01685b63"}

    def test_every_authority_pin(self):
        for key, want in self.PINS.items():
            self.assertEqual(C["authority"][key], want, key)

    def test_contract_version_is_1_4_3(self):
        self.assertEqual(C["authority"]["contract_version"], "1.4.3-candidate")

    def test_no_wall_clock_timestamp(self):
        blob = json.dumps(C)
        self.assertNotIn("generated_utc", blob)
        self.assertEqual(C["authority"]["authority_utc"], "2026-08-11T15:51:34Z")


@unittest.skipUnless(os.path.isdir(PKG), "package not built")
class DecisionMatrixCoverage(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(SIM, "specs",
                               "rescore-decision-matrix-v1.json"),
                  encoding="utf-8") as fh:
            self.mx = json.load(fh)

    def test_matrix_is_40_rescore_1_rerun_10_no_action(self):
        by = {}
        for row in self.mx["rows"]:
            by[row["decision"]] = by.get(row["decision"], 0) + 1
        self.assertEqual(by["RESCORE_REQUIRED"], 40)
        self.assertEqual(by["RERUN_REQUIRED"], 1)
        self.assertEqual(by["NO_ACTION"], 10)

    def test_every_rescore_estimand_is_produced(self):
        produced = {e["estimand_id"] for c in C["cells"] for e in c["estimands"]
                    if e["arms"] or e.get("counts")}
        produced |= {t["estimand_id"] for t in C["tier2_descriptive"]
                     if t.get("runs")}
        for row in self.mx["rows"]:
            if row["decision"] == "RESCORE_REQUIRED" and row["id"].startswith("EST-"):
                self.assertIn(row["id"], produced,
                              "%s produces no normative output" % row["id"])

    def test_the_single_rerun_issue_is_closed(self):
        rerun = [r["id"] for r in self.mx["rows"]
                 if r["decision"] == "RERUN_REQUIRED"]
        self.assertEqual(rerun, ["ISS-06"])
        self.assertEqual(
            C["iss06_channel_cooccurrence"]["priority_boolean_violations"], 0)

    def test_no_action_rows_produce_no_number(self):
        self.assertIsNone(C["iss05_closure"]["number_published"])
        for cell in C["cells"]:
            for e in cell["estimands"]:
                if e["estimand_id"] == "EST-A4-L4-01":
                    self.assertEqual(e["kind"], "not_applicable")
                    self.assertFalse(e["arms"])
                    self.assertIsNone(e["counts"])


@unittest.skipUnless(os.path.isdir(PKG), "package not built")
class NormativeCompleteness(unittest.TestCase):
    """A RESCORE_REQUIRED estimand must be PRODUCED, not merely accounted for.

    The first candidate package passed a weaker gate: it allowed a RESCORE row to
    be discharged by declaring it unsupported or Tier-2-only. Declaring a
    normative estimand undone is not the same as producing it, so these two
    tests exist to make that distinction a hard failure.
    """

    def setUp(self):
        with open(os.path.join(SIM, "specs",
                               "rescore-decision-matrix-v1.json"),
                  encoding="utf-8") as fh:
            self.mx = json.load(fh)
        self.rescore = [r["id"] for r in self.mx["rows"]
                        if r["decision"] == "RESCORE_REQUIRED"
                        and r["id"].startswith("EST-")]

    def _normative_output(self, estimand_id):
        """A real numeric result somewhere in the package, in the right place."""
        for cell in C["cells"]:
            for e in cell["estimands"]:
                if e["estimand_id"] != estimand_id:
                    continue
                if e["kind"] in ("unsupported", "not_applicable"):
                    continue
                if e["arms"] and any(n.get("value") is not None
                                     or n.get("observed_denominator")
                                     for n in e["arms"].values()):
                    return True
                if e.get("counts"):
                    return True
        for block in C.get("tier2_descriptive", []):
            if block.get("estimand_id") == estimand_id and block.get("runs"):
                return True
        return False

    def test_no_rescore_estimand_is_unsupported_tier2_or_placeholder(self):
        unsupported = {u["estimand_id"] for u in C.get("unsupported_estimands", [])
                       if u.get("kind") == "unsupported"}
        deferred = {t["estimand_id"] for t in C.get("tier2_only_estimands", [])}
        placeholder = {t["estimand_id"] for t in C.get("tier2_descriptive", [])
                       if not t.get("runs")}
        offenders = sorted(set(self.rescore)
                           & (unsupported | deferred | placeholder))
        self.assertEqual(offenders, [],
                         "RESCORE_REQUIRED estimands left undone: %s" % offenders)

    def test_40_rescore_coverage_requires_real_output(self):
        missing = [e for e in self.rescore if not self._normative_output(e)]
        self.assertEqual(missing, [],
                         "no normative output produced for: %s" % missing)
        self.assertEqual(len(self.rescore), 18 - 1,
                         "expected 17 RESCORE estimand rows (18 minus EST-A4-L4-01)")


@unittest.skipUnless(os.path.isdir(PKG), "package not built")
class DropDecisionUnitSeparation(unittest.TestCase):
    """D3 and D2 count DIFFERENT things about the same 249 drops.

    D3's unit is the received telemetry observation: a dropped packet never
    creates one, so EVERY drop lacks a D3 decision opportunity -> 249.

    D2's unit is the 60 s flow window: a drop's expected-arrival window either
    contains telemetry or does not, giving 248 native + 1 no-native + 0
    unresolved.

    Sourcing one family's number from the other is the defect these tests exist
    to reject: 1 is a window-level count and must never appear as the D3
    no-decision-opportunity figure.
    """

    def _cell(self, name):
        return next(c for c in C["cells"] if c["cell"] == name)

    def _estimand(self, cell_name, estimand_id):
        for e in self._cell(cell_name)["estimands"]:
            if e["estimand_id"] == estimand_id:
                return e
        raise AssertionError("%s not published in %s" % (estimand_id, cell_name))

    def test_a4_d3_drop_actions_are_249(self):
        e = self._estimand("A4-D3", "EST-F0-02")
        self.assertEqual(e["counts"]["dispositions"]["dropped"], 249)

    def test_d3_no_decision_opportunity_is_every_drop(self):
        e = self._estimand("A4-D3", "EST-A4-L2-02")
        drop = e["counts"]["drop_subtype"]
        self.assertEqual(drop["actions"], 249)
        self.assertEqual(drop["no_decision_opportunity"], 249,
                         "D3 has no decision point for ANY dropped packet")

    def test_d2_split_stays_in_the_flow_window_estimand(self):
        e = self._estimand("A4-D2", "EST-A4-L3-02")
        classes = e["counts"]["drop_opportunity_classes"]
        self.assertEqual(classes["native_decision_opportunity"], 248)
        self.assertEqual(classes["no_native_decision_opportunity"], 1)
        self.assertEqual(classes["unresolved"], 0)

    def test_the_d3_figure_is_not_borrowed_from_the_d2_split(self):
        d3 = self._estimand("A4-D3", "EST-A4-L2-02")["counts"]["drop_subtype"]
        d2 = self._estimand("A4-D2", "EST-A4-L3-02")["counts"][
            "drop_opportunity_classes"]
        self.assertNotEqual(d3["no_decision_opportunity"],
                            d2["no_native_decision_opportunity"],
                            "the D3 no-decision figure equals the D2 no-native "
                            "count: a window-level number has been reused as an "
                            "observation-level one")
        self.assertNotEqual(d3["no_decision_opportunity"],
                            d2["native_decision_opportunity"])
        self.assertEqual(d3["no_decision_opportunity"],
                         d2["native_decision_opportunity"]
                         + d2["no_native_decision_opportunity"]
                         + d2["unresolved"],
                         "every drop lacks a D3 opportunity, so the D3 figure is "
                         "the whole drop population, however D2 partitions it")

    def test_the_d2_classes_never_appear_under_the_d3_estimand(self):
        e = self._estimand("A4-D3", "EST-A4-L2-02")
        blob = json.dumps(e)
        for key in ("native_decision_opportunity",
                    "no_native_decision_opportunity",
                    "covered_by_alarming_expected_arrival_window"):
            self.assertNotIn(key, blob,
                             "%s is a D2 flow-window concept and must not appear "
                             "in the D3 subtype estimand" % key)


@unittest.skipUnless(os.path.isdir(PKG), "package not built")
class Iss06Invariants(unittest.TestCase):
    def test_corpus_invariants(self):
        i = C["iss06_channel_cooccurrence"]
        self.assertEqual(i["d3_alarms"], 1576)
        self.assertEqual(i["channel_labels"]["physical"], 281)
        self.assertEqual(i["channel_labels"].get("logical", 0), 0)
        self.assertEqual(i["channel_labels"]["security"], 1295)
        self.assertEqual(i["cooccurrence_rows"], 7)
        self.assertEqual(i["priority_boolean_violations"], 0)
        self.assertEqual(i["rows_missing_boolean_fields"], 0)

    def test_labels_sum_to_the_alarm_count(self):
        i = C["iss06_channel_cooccurrence"]
        self.assertEqual(sum(i["channel_labels"].values()), i["d3_alarms"])

    def test_cooccurrence_comes_from_the_boolean_fields(self):
        combos = C["iss06_channel_cooccurrence"]["boolean_combinations"]
        multi = {k: v for k, v in combos.items() if "+" in k}
        self.assertEqual(sum(multi.values()), 7)
        self.assertEqual(sum(combos.values()), 1576)


@unittest.skipUnless(os.path.isdir(PKG), "package not built")
class Aggregation(unittest.TestCase):
    def test_run_level_recomputes_macro_and_pooled(self):
        rl = {c["cell"]: c for c in R["cells"]}
        for cell in C["cells"]:
            for e in cell["estimands"]:
                for arm, node in e["arms"].items():
                    rows = next(x["arms"][arm] for x in rl[cell["cell"]]["estimands"]
                                if x["estimand_id"] == e["estimand_id"])
                    vals = [p["value"] for p in rows if p["value"] is not None]
                    if vals:
                        self.assertAlmostEqual(sum(vals) / len(vals), node["value"],
                                               places=12)
                    num = sum(p["numerator"] for p in rows)
                    den = sum(p["denominator"] for p in rows)
                    if den:
                        self.assertAlmostEqual(num / den, node["pooled_ratio"],
                                               places=12)
                    self.assertEqual(node["defined_run_count"], len(vals))
                    self.assertEqual(node["total_run_count"], 60)

    def test_run_macro_and_pooled_are_separate_fields(self):
        for cell in C["cells"]:
            for e in cell["estimands"]:
                for node in e["arms"].values():
                    self.assertIn("macro_mean_over_defined_runs", node)
                    self.assertIn("pooled_ratio", node)
                    self.assertNotIn("per_run", node)

    def test_ci_parameters(self):
        seen = 0
        for cell in C["cells"]:
            for e in cell["estimands"]:
                for node in e["arms"].values():
                    u = node.get("uncertainty")
                    if u:
                        seen += 1
                        self.assertEqual(u["resamples"], 2000)
                        self.assertEqual(u["seed"], 12345)
                        self.assertEqual(u["resampling_unit"], "run")
                        self.assertIn("percentile", u["method"])
                        self.assertIn("95%", u["method"])
                        self.assertLessEqual(u["ci_low"], u["ci_high"])
        self.assertGreater(seen, 0, "no interval was published at all")

    def test_pooled_ratios_never_carry_an_interval(self):
        for cell in P["cells"]:
            for e in cell["estimands"]:
                for node in e["arms"].values():
                    self.assertIsNone(node["uncertainty"])

    def test_all_zero_suppression_is_estimand_scoped(self):
        rl = {c["cell"]: c for c in R["cells"]}
        for cell in C["cells"]:
            for e in cell["estimands"]:
                for arm, node in e["arms"].items():
                    rows = next(x["arms"][arm] for x in rl[cell["cell"]]["estimands"]
                                if x["estimand_id"] == e["estimand_id"])
                    vals = [p["value"] for p in rows if p["value"] is not None]
                    if vals and all(v == 0.0 for v in vals):
                        self.assertIsNone(node["uncertainty"],
                                          "%s/%s" % (cell["cell"], arm))

    def test_a_nonzero_sibling_keeps_its_interval(self):
        """The scope test: suppression must not spill across estimands."""
        found = False
        for cell in C["cells"]:
            zero = [e for e in cell["estimands"]
                    for a, n in e["arms"].items()
                    if n["value"] == 0.0 and n["uncertainty"] is None]
            nonzero = [n for e in cell["estimands"] for n in e["arms"].values()
                       if n["value"] not in (None, 0.0) and n["uncertainty"]]
            if zero and nonzero:
                found = True
        self.assertTrue(found, "no cell exercises the estimand-level scope")

    def test_undefined_is_never_zero(self):
        for cell in R["cells"]:
            for e in cell["estimands"]:
                for rows in e["arms"].values():
                    for p in rows:
                        if p["value"] is None:
                            self.assertIsNotNone(p["undefined_reason_code"])


@unittest.skipUnless(os.path.isdir(PKG), "package not built")
class SchemaAndHonesty(unittest.TestCase):
    def test_no_nan_or_infinity(self):
        def walk(node):
            if isinstance(node, float):
                self.assertFalse(math.isnan(node) or math.isinf(node))
            elif isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        for doc in (C, R, P, M, V):
            walk(doc)

    def test_every_document_declares_a_schema(self):
        for doc in (C, R, P, M, V):
            self.assertIsInstance(doc["schema"], str)

    def test_no_estimand_is_left_unsupported(self):
        self.assertEqual(C["unsupported_estimands"], [])

    def test_a4_subtype_split_exists_and_never_double_credits(self):
        found = False
        for cell in C["cells"]:
            for e in cell["estimands"]:
                if e["estimand_id"] != "EST-A4-L2-02":
                    continue
                found = True
                self.assertIn("modification_detection_rate", e["arms"])
                self.assertIn("delay_detection_rate", e["arms"])
                self.assertIn("drop_subtype", e["counts"])
                mod = e["arms"]["modification_detection_rate"]
                dly = e["arms"]["delay_detection_rate"]
                self.assertLessEqual(
                    mod["observed_numerator"] + dly["observed_numerator"],
                    mod["observed_denominator"] + dly["observed_denominator"])
        self.assertTrue(found, "EST-A4-L2-02 is not published anywhere")

    def test_drop_subtype_publishes_no_rate(self):
        for cell in C["cells"]:
            for e in cell["estimands"]:
                if e["estimand_id"] == "EST-A4-L2-02":
                    self.assertNotIn("drop_detection_rate", e["arms"])
                    self.assertIn("no_decision_opportunity",
                                  e["counts"]["drop_subtype"])

    def test_l3_02_publishes_the_alarm_covered_numerator(self):
        found = False
        for cell in C["cells"]:
            for e in cell["estimands"]:
                if e["estimand_id"] != "EST-A4-L3-02":
                    continue
                found = True
                arm = e["arms"]["alarm_covered_drop_rate"]
                classes = e["counts"]["drop_opportunity_classes"]
                self.assertIn("covered_by_alarming_expected_arrival_window", classes)
                self.assertLessEqual(arm["observed_numerator"],
                                     arm["observed_denominator"])
                self.assertEqual(arm["observed_denominator"],
                                 classes["native_decision_opportunity"])
                if cell["cell"] == "A4-D2":
                    # The contract's known corpus split, reproduced exactly.
                    self.assertEqual(classes["native_decision_opportunity"], 248)
                    self.assertEqual(classes["no_native_decision_opportunity"], 1)
                    self.assertEqual(
                        classes["covered_by_alarming_expected_arrival_window"], 209)
                    self.assertEqual(arm["observed_numerator"], 209)
        self.assertTrue(found, "EST-A4-L3-02 is not published")

    def test_l3_01_uses_the_aggregate_d2_output_without_a_subtype_split(self):
        for cell in C["cells"]:
            for e in cell["estimands"]:
                if e["estimand_id"] != "EST-A4-L3-01":
                    continue
                self.assertEqual(set(e["arms"]),
                                 {"alarming_truth_positive_window_rate",
                                  "truth_positive_window_recall"})
                for arm in e["arms"]:
                    self.assertNotIn("modification", arm)
                    self.assertNotIn("delay", arm)

    def test_tier2_f5_and_f6_are_produced_and_quarantined(self):
        by = {t["estimand_id"]: t for t in C["tier2_descriptive"]}
        self.assertEqual(set(by), {"EST-F5-01", "EST-F6-01"})
        f5 = by["EST-F5-01"]
        self.assertEqual(len(f5["runs"]), 5)
        self.assertEqual(sorted(r["run_identity"] for r in f5["runs"]),
                         ["A6s-gate-off-r0", "A6s-gate-on-r0", "A6s-safe-large-r0",
                          "A6s-safe-r0", "A6s-unsupported-r0"])
        f6 = by["EST-F6-01"]
        self.assertTrue(f6["runs"])
        for row in f6["runs"]:
            self.assertTrue(row["anchor_agreement"])
            self.assertTrue(row["chain_intact"])
            self.assertTrue(row["tamper_mutation"]["detected"])
            self.assertTrue(row["tamper_mutation"]["detected_at_the_mutated_record"])
        for block in C["tier2_descriptive"]:
            self.assertIn("excluded_from_tier1", block)
            self.assertIsNone(block["uncertainty"])
        tier1 = {e["estimand_id"] for c in C["cells"] for e in c["estimands"]}
        self.assertFalse({"EST-F5-01", "EST-F6-01"} & tier1,
                         "a Tier-2 estimand leaked into the Tier-1 matrix")

    def test_f5_undefined_arm_is_not_zero(self):
        f5 = next(t for t in C["tier2_descriptive"]
                  if t["estimand_id"] == "EST-F5-01")
        off = next(r for r in f5["runs"] if r["run_identity"] == "A6s-gate-off-r0")
        self.assertEqual(off["scheduled_validation_opportunities"], 0)
        self.assertIsNone(off["value"])
        self.assertIsNotNone(off["undefined_reason_code"])

    def test_g8_substitution_invariance_holds(self):
        g8 = C["g8_substitution_invariance"]
        self.assertTrue(g8["pass"])
        self.assertEqual(g8["runs_compared"], 180)
        self.assertEqual(g8["value_differences"], [])

    def test_precision_target_is_recorded_as_unmet(self):
        p = C["precision_target"]
        self.assertEqual(p["cell"], "A1-D3")
        self.assertEqual(p["n_runs"], 60)
        self.assertGreater(p["arms_not_meeting_target"], 0,
                           "the historical 5% target must be recorded as unmet")
        self.assertIn("NOT met", p["statement"])

    def test_crn_is_measured_not_claimed(self):
        crn = C["common_random_numbers"]
        self.assertIn("strict_common_random_numbers_verified", crn)
        self.assertIsInstance(crn["strict_common_random_numbers_verified"], bool)
        self.assertIn("measured", crn["statement"])
        self.assertIn("within_scenario_crn_across_defences_verified", crn)
        self.assertFalse(crn["strict_common_random_numbers_verified"],
                         "strict CRN across all 20 cells must not be claimed")
        self.assertTrue(crn["within_scenario_crn_across_defences_verified"],
                        "the within-scenario pairing must be verified, not assumed")
        for seed in crn["per_seed"].values():
            self.assertEqual(seed["group_sizes"], [4, 4, 4, 4, 4])

    def test_checksum_file_covers_every_document(self):
        listed = {}
        with open(os.path.join(PKG, "CORRECTED_RESULTS.sha256"),
                  encoding="utf-8") as fh:
            for line in fh:
                digest, name = line.split()
                listed[name] = digest
        self.assertEqual(set(listed), set(FILES))
        for name, digest in listed.items():
            self.assertEqual(sha256(os.path.join(PKG, name)), digest, name)

    def test_the_builders_own_validation_is_green(self):
        self.assertEqual(V["verdict"], "GREEN")
        self.assertEqual(V["failed"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

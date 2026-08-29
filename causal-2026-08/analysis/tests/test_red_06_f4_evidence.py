#!/usr/bin/env python3
"""RED-6: the F4 denominator is the D1 rejection evidence event, not an observed
`rej` transition, and eligibility runs on telemetry source time.

Contract: ISS-14, ISS-15, INV-16, INV-19, INV-20; fixtures
FX-F4-CORPUS-CARDINALITY, FX-F4-INFLIGHT-ELIGIBILITY, FX-F4-PHYSICAL-LABEL-A1S15.

Every assertion below reads a field or value out of the TARGET's own output.
"""
import unittest
from collections import Counter

from red_common import RedTest, O, MISSING

F4_CELLS = ("A1-D3", "A2-D3", "A3-D3")


class TestF4Evidence(RedTest):

    # -- oracle/contract preconditions ---------------------------------------
    def test_precondition_contract_denominator_is_the_evidence_event(self):
        f4 = self.contract["f4_semantics"]
        self.assertEqual(f4["unit"], "d1_rejection_evidence_event")
        self.assertIn("rejection evidence events", f4["denominator"])
        self.assertNotIn("transition", f4["denominator"])
        self.assertEqual(f4["corpus_evidence"]["denominator_eligible"], 1302)

    # -- helpers -------------------------------------------------------------
    def _f4_totals(self):
        """Sum the TARGET's F4 block over the three command-side D3 cells."""
        totals = Counter()
        missing_runs = 0
        seen_runs = 0
        for cell in F4_CELLS:
            for run, _ev, _tr in O.corpus(cell + "-s??-r0-events.csv"):
                out = self.target_run(run)
                seen_runs += 1
                block = self.get_path(out, "F4", MISSING)
                if block is MISSING:
                    missing_runs += 1
                    continue
                for k in ("numerator", "denominator", "reported", "not_reported",
                          "no_reporting_opportunity"):
                    v = block.get(k)
                    if isinstance(v, int):
                        totals[k] += v
        return totals, missing_runs, seen_runs

    # -- defect tests --------------------------------------------------------
    def test_corpus_is_1302_reported_0_not_reported(self):
        """INV-19: the F4 family must exist and reproduce the corpus figures."""
        oracle = Counter()
        for sc in ("A1", "A2", "A3"):
            for run, ev, tr in O.corpus("%s-D3-s??-r0-events.csv" % sc):
                c, _ = O.f4_evidence_events(run, ev, tr, sc)
                oracle.update(c)
        self.assertEqual(
            (oracle["denominator_eligible"], oracle["reported"],
             oracle["not_reported"], oracle["no_reporting_opportunity"]),
            (1302, 1302, 0, 0),
            "oracle self-check: 1302 eligible evidence events, all reported")

        totals, missing_runs, seen_runs = self._f4_totals()
        expected = ("an F4 block on every command-side D3 run summing to "
                    "denominator 1302, reported 1302, not_reported 0, "
                    "no_reporting_opportunity 0")
        why = ("without a family F4 the D1+D3 ensemble reporting result is folded "
               "into the same effect-interval list that feeds D2/D3 detection "
               "metrics, so its denominator cannot be audited and it is published "
               "as twin behavioural detection")
        self.assertEqual(
            missing_runs, 0,
            self.defect("INV-19", "family F4 absent from the scorer output", expected,
                        "no F4 block in %d of %d run outputs"
                        % (missing_runs, seen_runs),
                        why, "oracle: 1302 evidence events across %s"
                        % ", ".join(F4_CELLS)))
        self.assertEqual(
            (totals["denominator"], totals["reported"], totals["not_reported"],
             totals["no_reporting_opportunity"]), (1302, 1302, 0, 0),
            self.defect("INV-19", "F4 corpus figures do not match", expected,
                        "denominator %d, reported %d, not_reported %d, "
                        "no_reporting_opportunity %d"
                        % (totals["denominator"], totals["reported"],
                           totals["not_reported"],
                           totals["no_reporting_opportunity"]),
                        why))

    def test_denominator_is_not_the_observed_rej_transition(self):
        """INV-19: the denominator basis must be declared and non-circular."""
        run = "A3-D3-s00-r0"
        out = self.target_run(run)
        expected = ("F4.denominator_basis = 'd1_rejection_evidence_event' and "
                    "F4.outcomes_supported including 'not_reported'")
        why = ("an observed-transition denominator is circular: the unit can only "
               "exist where the counter was already ground-visible, so not_reported "
               "is structurally unreachable and the result is forced by the "
               "definition instead of measured. The two denominators happen to "
               "coincide numerically on this corpus (both 1302), which is exactly "
               "why the defect must be caught structurally")

        basis = self.assert_field(
            out, "F4.denominator_basis", "INV-19",
            "F4 denominator basis is not declared", expected, why,
            "retracted basis: observed transitions of the `rej` field between "
            "consecutive tm.recv rows")
        self.assertEqual(
            basis, "d1_rejection_evidence_event",
            self.defect("INV-19", "circular denominator basis", expected,
                        "F4.denominator_basis = %r" % basis, why))

        outcomes = self.assert_field(
            out, "F4.outcomes_supported", "INV-19",
            "not_reported is not a representable outcome", expected, why)
        self.assertIn(
            "not_reported", outcomes,
            self.defect("INV-19", "not_reported unreachable", expected,
                        "outcomes_supported = %r" % (outcomes,), why))

    def test_inflight_observation_is_not_the_reporting_opportunity(self):
        """INV-20: eligibility must be declared as telemetry source time."""
        # What arrival-order eligibility would produce, from the artefacts:
        arrival = Counter()
        for sc in ("A2", "A3"):
            for run, ev, tr in O.corpus("%s-D3-s??-r0-events.csv" % sc):
                matched = O.match_actions_to_outcomes(run, ev, tr, sc)
                rejections = sorted(m["outcome_t"] for m in matched
                                    if m["outcome"] == "reject")
                obs = sorted([{"recv": r["t"], "seq": r["f"].get("seq")}
                              for r in ev if r["cat"] == "tm.recv"],
                             key=lambda o: o["recv"])
                alarms = {r["f"].get("tmSeq") for r in ev if r["cat"] == "d3.alarm"}
                for rt in rejections:
                    nxt = next((o for o in obs if o["recv"] > rt), None)
                    if nxt is None:
                        continue
                    arrival["reported" if nxt["seq"] in alarms
                            else "not_reported"] += 1
        self.assertEqual(
            arrival["not_reported"], 3,
            "oracle self-check: arrival-order eligibility mislabels exactly 3 "
            "in-flight packets")

        run = "A2-D3-s39-r0"
        out = self.target_run(run)
        expected = ("F4.eligibility_basis = 'telemetry_source_time'; an observation "
                    "is eligible only when its source time exceeds the rejection "
                    "timestamp")
        why = ("a packet sampled before the rejection cannot carry the increment no "
               "matter when it lands. Arrival-order eligibility invents %d spurious "
               "misses across the corpus and charges D3 with a measurement artefact"
               % arrival["not_reported"])
        basis = self.assert_field(
            out, "F4.eligibility_basis", "INV-20",
            "F4 eligibility basis is not declared", expected, why,
            "in-flight fixtures: A2-D3-s39 t=477200.006, A3-D3-s58 t=175420.009 "
            "and t=175510.009, each arriving 0.008-0.010 s after its rejection")
        self.assertEqual(
            basis, "telemetry_source_time",
            self.defect("INV-20", "arrival-time eligibility", expected,
                        "F4.eligibility_basis = %r" % basis, why))

        # and the run that contains one of the three in-flight cases must not
        # report a miss under the correct basis
        self.assert_value(
            out, "F4.not_reported", 0, "INV-20",
            "in-flight observation scored as a missed report",
            "F4.not_reported = 0 in %s under source-time eligibility" % run,
            why, "arrival-order eligibility would score 1 miss in this run")

    def test_numerator_is_not_filtered_on_the_channel_label(self):
        """INV-16: 7 of 1302 answering alarms carry the physical label."""
        labels = Counter()
        for sc in ("A1", "A2", "A3"):
            for run, ev, tr in O.corpus("%s-D3-s??-r0-events.csv" % sc):
                matched = O.match_actions_to_outcomes(run, ev, tr, sc)
                rejections = sorted(m["outcome_t"] for m in matched
                                    if m["outcome"] == "reject")
                obs = []
                for r in ev:
                    if r["cat"] != "tm.recv":
                        continue
                    obs.append({"src": r["t"] - float(r["f"].get("ageS", "0")),
                                "seq": r["f"].get("seq")})
                obs.sort(key=lambda o: o["src"])
                channel = {r["f"].get("tmSeq"): r["f"].get("channel")
                           for r in ev if r["cat"] == "d3.alarm"}
                for rt in rejections:
                    e = next((o for o in obs if o["src"] > rt), None)
                    if e is None:
                        continue
                    ch = channel.get(e["seq"])
                    if ch is not None:
                        labels[ch] += 1
        self.assertEqual(
            (labels["security"], labels["physical"]), (1295, 7),
            "oracle self-check: 1295 security-labelled and 7 physical-labelled")

        run = "A1-D3-s15-r0"
        out = self.target_run(run)
        expected = ("F4.numerator_channel_filtered = False, and the corpus numerator "
                    "counts all 1302 answering alarms (1295 security-labelled + 7 "
                    "physical-labelled)")
        why = ("Twin.cc:309 writes a single priority-selected label "
               "(physical > logical > security), so a co-occurring physical breach "
               "masks the security label of a real rejection report; filtering on "
               "the label silently loses %d genuine reporting events"
               % labels["physical"])
        filtered = self.assert_field(
            out, "F4.numerator_channel_filtered", "INV-16",
            "channel-filter policy is not declared", expected, why,
            "fixture A1-D3-s15-r0, tm.recv seq=8953 at t=89530.0169 is answered by "
            "a physical-labelled alarm")
        self.assertIs(
            filtered, False,
            self.defect("INV-16", "channel-label filter loses reporting events",
                        expected, "F4.numerator_channel_filtered = %r" % filtered,
                        why))

        totals, _missing, _seen = self._f4_totals()
        self.assertEqual(
            totals["numerator"], 1295 + 7,
            self.defect("INV-16", "corpus numerator excludes the masked reports",
                        expected, "corpus F4 numerator = %d" % totals["numerator"],
                        why, "a security-only filter would give 1295"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

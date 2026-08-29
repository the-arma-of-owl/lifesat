#!/usr/bin/env python3
"""RED-9: the scorer output must satisfy the contract's exact output schema.

Contract: ISS-24, ISS-25, INV-30, INV-31; output_schema (closed key sets, typed
fields, non-negative integer counts, non-empty cells, mandatory per-run records,
mandatory provenance).
"""
import unittest

from red_common import RedTest, O

PATTERN = "A4-D2-s??-r0-events.csv"


class TestOutputSchema(RedTest):

    def setUp(self):
        self.schema = self.contract["output_schema"]
        self.why = ("the output schema is a closed, typed key set; without it a "
                    "published number cannot be located, traced or re-verified, and "
                    "a malformed count would pass unnoticed")

    def _doc(self, ref, title, expected):
        return self.corpus_or_fail(PATTERN, ref, title, expected, self.why)

    def test_output_has_the_required_root_keys(self):
        required = self.schema["required_root_keys"]
        expected = "root keys %s" % required
        doc = self._doc("INV-31", "scorer output does not match the output schema",
                        expected)
        missing = [k for k in required if k not in doc]
        self.assertEqual(
            missing, [],
            self.defect("INV-31", "scorer output does not match the output schema",
                        expected, "emitted %s" % sorted(doc.keys()), self.why,
                        "missing: %s" % missing))

    def test_output_carries_full_provenance(self):
        required = self.schema["provenance"]["required_fields"]
        expected = "a provenance block carrying %s" % required
        doc = self._doc("INV-31", "provenance absent from the scorer output", expected)
        prov = self.assert_field(doc, "provenance", "INV-31",
                                 "provenance absent from the scorer output",
                                 expected, self.why)
        missing = [k for k in required if k not in prov]
        self.assertEqual(
            missing, [],
            self.defect("INV-31", "provenance incomplete", expected,
                        "provenance keys %s" % sorted(prov.keys()), self.why,
                        "missing: %s" % missing))
        self.assertEqual(
            prov["contract_version"], O.ACCEPTED_CONTRACT_VERSION,
            self.defect("INV-31", "provenance names the wrong contract", expected,
                        "contract_version = %r" % prov["contract_version"], self.why))

    def test_counts_are_non_negative_integers(self):
        expected = ("every numerator, denominator, defined_run_count and "
                    "total_run_count a non-negative int; a negative, fractional or "
                    "boolean value is fail-closed")
        doc = self._doc("INV-31", "no cell structure to validate counts against",
                        expected)
        bad = []
        for cell in doc.get("cells", []):
            for res in cell.get("estimand_results", []):
                for k in ("numerator", "denominator", "defined_run_count",
                          "total_run_count"):
                    v = res.get(k)
                    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                        bad.append("%s.%s=%r" % (res.get("estimand_id"), k, v))
        self.assertEqual(
            bad, [],
            self.defect("INV-31", "malformed count in the output", expected,
                        "offending fields: %s" % bad[:5], self.why))

    def test_per_run_records_are_present_for_every_run(self):
        expected = ("every estimand result carrying one per_run record per "
                    "run_identity in provenance.run_identities, with "
                    "len(per_run) == total_run_count")
        doc = self._doc("INV-31", "per-run records cannot be emitted", expected)
        runs = set(doc["provenance"]["run_identities"])
        for cell in doc["cells"]:
            for res in cell["estimand_results"]:
                per = res.get("per_run")
                self.assertIsInstance(
                    per, list,
                    self.defect("INV-31", "per-run records missing", expected,
                                "per_run = %r in %s" % (per, res.get("estimand_id")),
                                self.why))
                self.assertEqual(
                    len(per), res["total_run_count"],
                    self.defect("INV-31", "per-run record count mismatch", expected,
                                "%d record(s) for total_run_count = %d"
                                % (len(per), res["total_run_count"]), self.why))
                ids = [p["run_identity"] for p in per]
                self.assertEqual(
                    len(set(ids)), len(ids),
                    self.defect("INV-31", "duplicate per-run record", expected,
                                "%d record(s), %d unique" % (len(ids), len(set(ids))),
                                self.why))
                self.assertTrue(
                    set(ids) <= runs,
                    self.defect("INV-31", "per-run record for an undeclared run",
                                expected, "unknown: %s" % sorted(set(ids) - runs)[:3],
                                self.why))

    def test_empty_cells_are_rejected(self):
        expected = ("a non-empty cells[] array; a scorer output covering no cell is "
                    "fail-closed, and each cell carries at least one estimand result")
        doc = self._doc("INV-31", "no cells array exists, so emptiness cannot be "
                                  "rejected", expected)
        cells = doc.get("cells")
        self.assertTrue(
            isinstance(cells, list) and len(cells) > 0,
            self.defect("INV-31", "empty cells array", expected,
                        "cells = %r" % (cells,), self.why))
        for cell in cells:
            self.assertTrue(
                cell.get("estimand_results"),
                self.defect("INV-31", "cell with no estimand result", expected,
                            "cell %r" % cell.get("cell"), self.why))


if __name__ == "__main__":
    unittest.main(verbosity=2)

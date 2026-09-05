#!/usr/bin/env python3
"""Shared base for the RED regression tests.

The suite is TARGET-AGNOSTIC. It asserts contract-required fields and values on
whatever scorer is under test:

  LIFESAT_RED_TARGET=current    -> analysis/score.py        (must be RED)
  LIFESAT_RED_TARGET=reference  -> tests/reference_scorer.py (must be GREEN)

A test may never manufacture a failure. Forbidden constructs: comparing a value
with itself, asserting against a literal empty container, or pinning an oracle
figure to a value the oracle does not produce. Every defect assertion reads a
field or value out of the TARGET's own output.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.dirname(HERE)
SIM = os.path.dirname(ANALYSIS)
for p in (HERE, ANALYSIS):
    if p not in sys.path:
        sys.path.insert(0, p)

import contract_oracle as O          # noqa: E402

TARGET_NAME = os.environ.get("LIFESAT_RED_TARGET", "current")

if TARGET_NAME == "reference":
    import reference_scorer as TARGET          # noqa: E402
    TARGET_LABEL = "reference_scorer.py (contract-conformant)"
    TARGET_IMPORT_ERROR = None
else:
    try:
        import score as TARGET                 # noqa: E402
        TARGET_IMPORT_ERROR = None
    except Exception as exc:                   # pragma: no cover
        TARGET = None
        TARGET_IMPORT_ERROR = exc
    TARGET_LABEL = "analysis/score.py (pre-correction)"

MISSING = object()


class RedTest(unittest.TestCase):
    """Base class carrying the diagnostic vocabulary."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.contract = O.contract()
        cls.target = TARGET
        cls.target_label = TARGET_LABEL
        if TARGET is None:
            raise AssertionError("scorer under test could not be imported: %r"
                                 % (TARGET_IMPORT_ERROR,))

    # -- diagnosis -----------------------------------------------------------
    def defect(self, ref, title, expected, observed, why, evidence=""):
        msg = ["",
               "CONTRACT DEFECT %s - %s" % (ref, title),
               "  scorer under test : %s" % self.target_label,
               "  contract requires : %s" % expected,
               "  scorer produced   : %s" % observed,
               "  why this is wrong : %s" % why]
        if evidence:
            msg.append("  evidence          : %s" % evidence)
        return "\n".join(msg)

    # -- target access -------------------------------------------------------
    def call_target(self, attr, *a, **kw):
        """Invoke a target API; a missing API or a crash becomes a diagnosis."""
        fn = getattr(self.target, attr, None)
        if fn is None:
            return MISSING
        try:
            return fn(*a, **kw)
        except Exception as exc:
            self.fail("scorer %s.%s raised %s: %s"
                      % (self.target_label, attr, type(exc).__name__, exc))

    def target_run(self, run, end_time=604800.0):
        ep = os.path.join(O.RESULTS, run + "-events.csv")
        tp = os.path.join(O.RESULTS, run + "-truth.csv")
        out = self.call_target("score_run", ep, tp, end_time)
        if out is MISSING:
            self.fail("scorer under test exposes no score_run()")
        return out

    def target_corpus(self, pattern):
        """Corpus-level contract output, or MISSING when the API does not exist."""
        return self.call_target("score_corpus", pattern)

    def get_path(self, obj, path, default=MISSING):
        """Fetch a dotted path out of a nested target result."""
        cur = obj
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def assert_field(self, obj, path, ref, title, expected, why, evidence=""):
        """The target output must expose `path` at all."""
        got = self.get_path(obj, path)
        self.assertIsNot(
            got, MISSING,
            self.defect(ref, title, expected,
                        "no `%s` field in the output (top-level keys: %s)"
                        % (path, sorted(obj.keys()) if isinstance(obj, dict) else obj),
                        why, evidence))
        return got

    def assert_value(self, obj, path, want, ref, title, expected, why, evidence=""):
        got = self.assert_field(obj, path, ref, title, expected, why, evidence)
        self.assertEqual(
            got, want,
            self.defect(ref, title, expected, "`%s` = %r" % (path, got), why, evidence))
        return got

    def corpus_or_fail(self, pattern, ref, title, expected, why, evidence=""):
        out = self.target_corpus(pattern)
        self.assertIsNot(
            out, MISSING,
            self.defect(ref, title, expected,
                        "the scorer exposes no score_corpus(); it scores one run in "
                        "isolation and has no cell-level or corpus-level output at all",
                        why, evidence))
        return out

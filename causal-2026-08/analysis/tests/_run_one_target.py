#!/usr/bin/env python3
"""Run the RED suite once against LIFESAT_RED_TARGET and emit JSON on stdout.

Invoked by run_red_tests.py as a subprocess so that `current` and `reference`
each get a clean import of their own scorer.
"""
import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MODULES = [
    "test_red_01_a3_identity",
    "test_red_02_families",
    "test_red_03_effect_window",
    "test_red_04_d2_native_unit",
    "test_red_05_a4_accounting",
    "test_red_06_f4_evidence",
    "test_red_08_aggregation",
    "test_red_09_output_schema",
]


def flat(t):
    if isinstance(t, unittest.TestSuite):
        for x in t:
            yield from flat(x)
    else:
        yield t


def name_of(t):
    return "%s.%s" % (t.__class__.__module__, t._testMethodName)


def main():
    loader = unittest.TestLoader()
    cases = []
    for m in MODULES:
        for c in flat(loader.loadTestsFromName(m)):
            if c.__class__.__name__ == "_FailedTest":
                raise SystemExit("import failure in %s:\n%s" % (m, c))
            cases.append(c)
    suite = unittest.TestSuite(cases)
    buf = io.StringIO()
    res = unittest.TextTestRunner(stream=buf, verbosity=0).run(suite)
    print(json.dumps({
        "target": os.environ.get("LIFESAT_RED_TARGET", "current"),
        "all": [name_of(c) for c in cases],
        "failures": {name_of(t): msg for t, msg in res.failures},
        "errors": {name_of(t): msg for t, msg in res.errors},
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

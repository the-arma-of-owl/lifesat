#!/usr/bin/env python3
"""Run the Task-4/Task-5 production-only modules and emit JSON on stdout.

Separate from _run_one_target.py (a frozen Task-3 asset) so that the frozen
module list stays untouched.
"""
import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MODULES = ["test_green_01_f4_counter", "test_green_02_semantic_guards"]


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
    res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(
        unittest.TestSuite(cases))
    print(json.dumps({"all": [name_of(c) for c in cases],
                      "failures": {name_of(t): msg for t, msg in res.failures},
                      "errors": {name_of(t): msg for t, msg in res.errors}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

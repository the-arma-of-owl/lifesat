"""DTaaS smoke test.

Extended after the independent review. The previous version had two blind spots:
  - only D1 was tested, D2 was never run (D2 was broken)
  - containment was measured with `git status --porcelain`, which could not see
    writes to ignored paths (Python bytecode)
"""
import os, sys, subprocess, pathlib
sys.path.insert(0, ".")
import config as C
from instance import Instance, validate, build_argv, BadRequest, verify_code_identity
from pathlib import Path

ok = True
def check(name, cond):
    global ok
    print(("  OK   " if cond else "  FAIL ") + name)
    ok = ok and bool(cond)
    return cond

def skip(name, why):
    """Not a failure: the check needs something this checkout cannot supply."""
    print("  SKIP " + name + "\n        -> " + why)

def tree_snapshot():
    """Path -> SHA-256 map of the accepted tree, ignored files included.

    Comparing the set of file names alone is not enough: if the content of an
    existing file changes, the name set stays the same and the violation is invisible.
    """
    import hashlib
    snap = {}
    for p in C.CODE.rglob("*"):
        if p.is_file() and ".git/" not in str(p):
            try: snap[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError: snap[str(p)] = "<unreadable>"
    return snap

print(" -- identity -- ")
ident = None
if not (os.environ.get("LIFESAT_EXPECTED_COMMIT") and os.environ.get("LIFESAT_EXPECTED_BIN")):
    skip("code identity",
         "no revision pinned. Set LIFESAT_EXPECTED_COMMIT and LIFESAT_EXPECTED_BIN "
         "to the revision and binary digest being deployed.")
else:
    try:
        ident = verify_code_identity()
        check("code identity matches the pinned commit and binary digest", True)
    except Exception as e:
        check(f"code identity could not be verified: {e}", False)

print(" -- input validation -- ")
for bad in ({"scenario":"NOPE","defence":"D1"}, {"scenario":"A1","defence":"D9"},
            {"scenario":"A1","defence":"D1","seed":-1}, {"scenario":"A1","defence":"D1","horizon":0}):
    try:
        validate(bad); check(f"must be rejected: {bad}", False)
    except BadRequest: check(f"reddedildi: {list(bad.values())}", True)

print(" -- argv containment and defence keys -- ")
a = build_argv(validate({"scenario":"A1","defence":"D3","seed":1}), Path("/tmp/inst"))
check("collector output redirected into the instance directory",
      any('collector.outputDir="/tmp/inst/results"' in x for x in a))
check("result-dir redirected into the instance directory", "--result-dir=/tmp/inst/omnetpp-native" in a)
check("twin enabled under D3", "--*.twin.enabled=true" in a)
d2 = build_argv(validate({"scenario":"A1","defence":"D2","seed":1}), Path("/tmp/inst"))
check("D2 thresholdFile bound to the instance directory",
      any('flow.thresholdFile="/tmp/inst/results/d2_thresholds.txt"' in x for x in d2))
check("D2 windowSize supplied", "--*.flow.windowSize=60s" in d2)

print(" -- OVERRIDES equivalence with run_matrix.py -- ")
sys.path.insert(0, str(C.CODE / "analysis"))
src = (C.CODE / "analysis" / "run_matrix.py").read_text()
import ast, re
ov_src = ast.literal_eval(re.search(r"^OVERRIDES\s*=\s*(\{.*?\n\})", src, re.S | re.M).group(1))
for d in C.DEFENCES:
    mine = set(C.OVERRIDES[d]) | ({"*.flow.thresholdFile"} if d == "D2" else set())
    check(f"{d} key set identical to run_matrix", mine == set(ov_src[d]))

print(" -- real run: D1 and D2 -- ")
have_binary = C.BIN.exists()
if not have_binary:
    skip("real run of D1 and D2",
         f"the simulator has not been built: {C.BIN} does not exist. "
         "Build it with OMNeT++ 6.4.0 and INET 4.7.0 first; see matrix-2026-07/README.md.")
C.INSTANCES.mkdir(parents=True, exist_ok=True)
before = tree_snapshot()
for defence in (("D1", "D2") if have_binary else ()):
    inst = Instance(validate({"scenario":"B0","defence":defence,"seed":0,"horizon":3600}))
    try:
        inst.provision(); inst.run(timeout=300)
    except Exception as e:
        inst.status = "failed"; inst.error = repr(e)
    good = inst.status == "done" and inst.result and "F0" in inst.result
    check(f"{defence} ran and was scored ({inst.status})", good)
    if not good and inst.error: print("        ->", inst.error[:220])
    if inst.status in ("done", "failed"): inst.teardown()
after = tree_snapshot()

print(" -- containment (ignored files included) -- ")
added = sorted(set(after) - set(before))
removed = sorted(set(before) - set(after))
changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
check(f"no file added to the accepted tree ({len(added)})", not added)
check(f"no file removed from the accepted tree ({len(removed)})", not removed)
check(f"no content changed in the accepted tree ({len(changed)})", not changed)
for p in (added + removed + changed)[:5]: print("        !", p)

print(" -- lifecycle -- ")
inst = Instance(validate({"scenario":"B0","defence":"D1","seed":1,"horizon":3600}))
inst.provision(); inst.status = "running"
try:
    inst.teardown(); check("tearing down a running instance is refused", False)
except BadRequest: check("tearing down a running instance is refused", True)
inst.status = "done"; inst.teardown()
check("completed instance torn down", not inst.dir.exists())

print("\nRESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)

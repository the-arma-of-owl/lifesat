#!/usr/bin/env python3
"""p4_authority.py — the pinned read-only inputs of the Phase 4 repair.

Four inputs, each pinned, NONE of them ever written by this package:

  * the historical scoring contract and its seal — byte-exact;
  * the historical corrected package `results-v2-corrected/` — the rollback
    target, which must stay byte-exact through the whole phase;
  * the immutable raw corpus: 1020 runs from the accepted raw tree plus 180
    from the accepted ISS-06 rerun, exactly the 1200 the historical package
    consumed, taken from its own INPUT_MANIFEST with per-run digests;
  * the PRE-REPAIR production scorer, so the repair can be shown to be minimal.

The candidate scorer lives inside THIS root. The historical v7 tree is not
edited: it is historical authority, and a repair is a candidate until the
accepting party says otherwise. The repaired file is nonetheless the ONE
scorer used for rescoring — there is no side scorer, and no second code path.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

sys.dont_write_bytecode = True

V7_ROOT = "/home/topya/lifesat_correction_round_v7/simulation"
V7_ANALYSIS = os.path.join(V7_ROOT, "analysis")
HISTORICAL_PACKAGE = os.path.join(V7_ROOT, "results-v2-corrected")
OLD_RAW = os.path.join(V7_ROOT, "results")
RERUN_RAW = os.path.join(V7_ROOT, "results-v2-iss06")

PHASE4_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATE_SCORER = os.path.join(PHASE4_ROOT, "candidate_scorer")
SUCCESSOR_RELATIVE = "successor/PHASE4_SUCCESSOR_RESULT_PACKAGE.json"

# Pinned from the historical package's own VALIDATION.json / builder pin table.
EXPECT_CONTRACT_JSON_SHA256 = \
    "913848492f82502f5a28243534eaa3e2e19c3c023ebd8b49df8027b8ccf54e95"
EXPECT_SEAL_SHA256 = \
    "5c575f3cee35000b4da45c63312ea166ed632b6a4efd7e3fc85efe707ea8d813"
EXPECT_PRE_REPAIR_SCORER_SHA256 = \
    "de16e29c73b7d2dcac87a114d755e130874eb892215be0947134afcf6f61a4cc"
EXPECT_OLD_RAW_TREE_SHA256 = \
    "09893fc41cd5fab122b2d956bda46664d60d3b9f33aa68f95d4d41b408711c16"
EXPECT_RERUN_TREE_SHA256 = \
    "f7e1d5fe90340d8bef2a0a512322d6b6017b39c56c1cec20a9531a0a01685b63"

# The historical corrected package, as the rollback target.
HISTORICAL_MEMBERS = ("CORRECTED_RESULTS.json", "POOLED_RESULTS.json",
                      "RUN_LEVEL_RESULTS.json", "INPUT_MANIFEST.json",
                      "VALIDATION.json", "CORRECTED_RESULTS.sha256")

SOURCE_ROOTS = {"results": OLD_RAW, "rerun": RERUN_RAW,
                "results-v2-iss06": RERUN_RAW}


class AuthorityError(Exception):
    """A pinned input did not match its pinned identity."""


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, payload):
    """Deterministic JSON: sorted keys, fixed indent, trailing newline."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    return sha256_file(path)


def load_json(path, expect=None):
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if expect is not None and not isinstance(payload, expect):
        raise AuthorityError(f"{path}: root is {type(payload).__name__}")
    return payload


def scorer_digest(analysis_root):
    """The production scoring code actually used, by the ACCEPTED recipe.

    Reproduced from `scoring/output.py:scorer_digest` deliberately: the digest
    of the repaired scorer has to be comparable with the historical pin, and a
    different recipe would make the comparison meaningless.
    """
    parts = [os.path.join(analysis_root, "score.py")]
    package = os.path.join(analysis_root, "scoring")
    for name in sorted(os.listdir(package)):
        if name.endswith(".py"):
            parts.append(os.path.join(package, name))
    digest = hashlib.sha256()
    for path in parts:
        digest.update(("%s  %s\n" % (sha256_file(path),
                                     os.path.relpath(path, analysis_root))
                       ).encode("utf-8"))
    return digest.hexdigest()


def tree_digest(root):
    """Digest of a raw tree: every file, by relative path and content."""
    entries = []
    for base, _dirs, files in os.walk(root):
        for name in sorted(files):
            full = os.path.join(base, name)
            entries.append((os.path.relpath(full, root), sha256_file(full)))
    entries.sort()
    digest = hashlib.sha256()
    for relative, file_digest in entries:
        digest.update(("%s  %s\n" % (file_digest, relative)).encode("utf-8"))
    return digest.hexdigest(), len(entries)


_CACHE = {}


def historical():
    """The historical corrected package and its pinned authority."""
    if "historical" not in _CACHE:
        validation = load_json(os.path.join(HISTORICAL_PACKAGE,
                                            "VALIDATION.json"), dict)
        authority = validation["authority"]
        for key, pin in (("contract_json_sha256", EXPECT_CONTRACT_JSON_SHA256),
                         ("seal_sha256", EXPECT_SEAL_SHA256),
                         ("scorer_sha256", EXPECT_PRE_REPAIR_SCORER_SHA256),
                         ("old_raw_tree_sha256", EXPECT_OLD_RAW_TREE_SHA256),
                         ("rerun_tree_sha256", EXPECT_RERUN_TREE_SHA256)):
            if authority.get(key) != pin:
                raise AuthorityError(
                    f"historical {key} is {authority.get(key)}, not the pin {pin}")
        _CACHE["historical"] = {
            "authority": authority,
            "digests": {name: sha256_file(os.path.join(HISTORICAL_PACKAGE, name))
                        for name in HISTORICAL_MEMBERS},
            "validation": validation,
        }
    return _CACHE["historical"]


def pre_repair_scorer_sha256():
    """The scorer digest of the HISTORICAL v7 tree, live."""
    return scorer_digest(V7_ANALYSIS)


def candidate_scorer_sha256():
    """The scorer digest of the REPAIRED candidate tree, live."""
    return scorer_digest(CANDIDATE_SCORER)


def corpus():
    """The immutable 1200-run input set, from the historical INPUT_MANIFEST.

    The run list is READ, never rebuilt: the successor must consume exactly the
    corpus the historical package consumed, or "the only thing that changed is
    the scorer" is not a statement anyone can check.
    """
    if "corpus" not in _CACHE:
        manifest = load_json(os.path.join(HISTORICAL_PACKAGE,
                                          "INPUT_MANIFEST.json"), dict)
        runs = manifest["runs"]
        if manifest["selected_runs"] != len(runs):
            raise AuthorityError(
                f"manifest declares {manifest['selected_runs']} selected runs "
                f"but lists {len(runs)}")
        _CACHE["corpus"] = {"manifest": manifest, "runs": runs}
    return _CACHE["corpus"]


def run_paths(run):
    """Absolute (events, truth) paths for a manifest run row."""
    root = SOURCE_ROOTS.get(run["source"])
    if root is None:
        raise AuthorityError(f"unknown source root {run['source']!r}")
    return (os.path.join(root, run["identity"] + "-events.csv"),
            os.path.join(root, run["identity"] + "-truth.csv"))


def verify_run_inputs(run):
    """The run's raw bytes are the ones the historical manifest recorded."""
    events, truth = run_paths(run)
    problems = []
    for path, pin, label in ((events, run["events_sha256"], "events"),
                             (truth, run["truth_sha256"], "truth")):
        if not os.path.exists(path):
            problems.append(f"{label} absent: {path}")
        elif sha256_file(path) != pin:
            problems.append(f"{label} {sha256_file(path)} != manifest {pin}")
    return problems


def main():
    info = historical()
    print("historical corrected package")
    for key, value in sorted(info["authority"].items()):
        print(f"  {key:<26} {value}")
    print()
    print(f"pre-repair scorer (v7 tree)  {pre_repair_scorer_sha256()}")
    print(f"candidate scorer (repaired)  {candidate_scorer_sha256()}")
    print()
    data = corpus()
    print(f"corpus runs                  {len(data['runs'])}")
    sources = {}
    for run in data["runs"]:
        sources[run["source"]] = sources.get(run["source"], 0) + 1
    for name, count in sorted(sources.items()):
        print(f"  source {name:<20} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

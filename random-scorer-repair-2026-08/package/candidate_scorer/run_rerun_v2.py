#!/usr/bin/env python3
"""ISS-06 rerun fleet driver (contract v1.4.3) — fail-closed.

Every destructive possibility is closed by construction rather than by care:

  * the plan is GENERATED here, not accepted from the caller. There is no way to
    pass a cell, a scenario or a seed on the command line, so an operator cannot
    widen the scope by typing.
  * the output root must NOT already exist and is created atomically; a second
    invocation against the same root fails instead of merging into it.
  * simulation/results/ is never a destination.
  * before each run the three target files must be absent; nothing is overwritten.
  * the first process failure stops new work from being launched.
  * success requires completed == 180, failed == 0, duplicate == 0, missing == 0.

analysis/run_matrix.py is deliberately untouched: it drives the accepted matrix
and must stay bit-stable.
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
OLD_RESULTS = os.path.realpath(os.path.join(SIM, "results"))
BINARY = os.path.join(SIM, "out", "clang-release", "lifesat")

# ── authority: the contract's ISS-06 affected_cells, and nothing else ───────
AUTHORISED_CELLS = {"A1-D3": "A1", "A2-D3": "A2", "A3-D3": "A3"}
REQUIRED_SEEDS = frozenset(range(60))
EXPECTED_RUNS = len(AUTHORISED_CELLS) * len(REQUIRED_SEEDS)      # 180
MAX_CONCURRENCY = 16
SUFFIXES = ("-events.csv", "-truth.csv", "-anchor.txt")

# identical to the accepted matrix run; only outputDir differs
OVERRIDES_D3 = {"*.sat.commandAuthEnabled": "true", "*.gs.signCommands": "true",
                "*.flow.enabled": "false", "*.twin.enabled": "true"}
ALWAYS = {"*.rnd.enabled": "true"}


SEAL_DIR = ("/home/topya/lifesat_backups/checkpoints/"
            "20260811T155134Z-scoring-contract-v143-accepted")

# Exact bytes this fleet is authorised to run against. Every one is verified
# BEFORE the output root is created, so a mismatch leaves no trace on disk.
AUTHORITY_PINS = {
    "specs/scoring-contract-v1.json":
        "913848492f82502f5a28243534eaa3e2e19c3c023ebd8b49df8027b8ccf54e95",
    "specs/scoring-contract-v1.md":
        "9a09cbfc72a8fe1c3d145075e1032b64d87d7eeb21acf8be338f5c190baabe15",
    "specs/SCORING_CONTRACT.sha256":
        "c57916ab067e0e1cac6d2945d1959730a6016418b8d5a15023a83b8ffbc9d60a",
    "src/Twin.cc":
        "d173ab4300031e27c288bee987d722f8e9448c375e19d32bba4f6e38ac294c1a",
    "out/clang-release/lifesat":
        "edbe53b815e83ad169ef70473785f4b5291b532620326ac3c899abfa0b35e975",
    "simulations/lifesat.ini":
        "73308f558d55f52687f77602b3ec86e71d15495acd18728f365061a3b37ff0d9",
    "analysis/run_matrix.py":
        "6f5b9963ccf0bed92c04e1f05335b3749eb05c7e026760c531299dee764c5cfd",
}
SEAL_PIN = "5c575f3cee35000b4da45c63312ea166ed632b6a4efd7e3fc85efe707ea8d813"
SRC_TREE_PIN = "a9ee7cc35fd7030c6dda0457541e14b59beab16a6e39f38722a7a402c502c8e8"
ACCEPTED_CONTRACT_VERSION = "1.4.3-candidate"


class AuthorityError(Exception):
    """The tree is not the exact package this fleet was authorised against."""


class PlanError(Exception):
    """A plan that is not exactly the authorised 180 runs."""


class OutputError(Exception):
    """Anything that would overwrite or reuse existing output."""


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def tree_digest(root):
    """lifesat-tree-digest/v1 over a directory."""
    rows = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            rows.append((os.path.relpath(path, root).replace(os.sep, "/"), path))
    rows.sort(key=lambda r: r[0].encode("utf-8"))
    digest = hashlib.sha256()
    for rel, path in rows:
        digest.update(("%s  %s\n" % (sha256(path), rel)).encode("utf-8"))
    return digest.hexdigest()


def verify_authority():
    """Pin every input the fleet depends on. Raises before anything is created.

    Pinning the seal is not enough on its own: the seal is a claim ABOUT a
    contract, so the claim is also checked against the contract on disk.
    """
    problems = []
    for rel, expected in sorted(AUTHORITY_PINS.items()):
        path = os.path.join(SIM, rel)
        if not os.path.exists(path):
            problems.append("%s is missing" % rel)
            continue
        got = sha256(path)
        if got != expected:
            problems.append("%s sha256 %s != pinned %s" % (rel, got, expected))

    seal_path = os.path.join(SEAL_DIR, "ACCEPTANCE_SEAL.json")
    if not os.path.exists(seal_path):
        problems.append("acceptance seal is missing at %s" % seal_path)
    else:
        got = sha256(seal_path)
        if got != SEAL_PIN:
            problems.append("seal sha256 %s != pinned %s" % (got, SEAL_PIN))
        else:
            with open(seal_path, encoding="utf-8") as fh:
                seal = json.load(fh)
            if seal.get("accepted_contract_version") != ACCEPTED_CONTRACT_VERSION:
                problems.append("seal accepts %r, not %r"
                                % (seal.get("accepted_contract_version"),
                                   ACCEPTED_CONTRACT_VERSION))
            claimed = seal.get("contract_json_sha256")
            actual = AUTHORITY_PINS["specs/scoring-contract-v1.json"]
            if claimed != actual:
                problems.append("seal claims contract %s but the pinned contract "
                                "is %s" % (claimed, actual))
            if not (seal.get("accepted_by_user") and seal.get("verified_by_hermes")):
                problems.append("seal is not both user-accepted and Hermes-verified")

    src_root = os.path.join(SIM, "src")
    got_tree = tree_digest(src_root)
    if got_tree != SRC_TREE_PIN:
        problems.append("src tree digest %s != pinned %s" % (got_tree, SRC_TREE_PIN))

    if problems:
        raise AuthorityError("authority pin mismatch; nothing was created:\n  - "
                             + "\n  - ".join(problems))
    return {"contract_version": ACCEPTED_CONTRACT_VERSION,
            "seal": seal_path, "seal_sha256": SEAL_PIN,
            "src_tree_digest": got_tree,
            "pins": dict(AUTHORITY_PINS)}


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── plan ───────────────────────────────────────────────────────────────────
def build_plan():
    """The fleet generates its own plan: 3 cells x 60 seeds = 180 identities."""
    return [{"cell": cell, "scenario": scenario, "seed": seed,
             "identity": "%s-s%02d-r0" % (cell, seed)}
            for cell, scenario in sorted(AUTHORISED_CELLS.items())
            for seed in sorted(REQUIRED_SEEDS)]


def validate_plan(plan):
    """Fail closed on anything that is not exactly the authorised fleet."""
    if len(plan) != EXPECTED_RUNS:
        raise PlanError("plan has %d runs, expected %d" % (len(plan), EXPECTED_RUNS))

    identities = [r["identity"] for r in plan]
    dupes = sorted({i for i in identities if identities.count(i) > 1})
    if dupes:
        raise PlanError("duplicate run identities: %s" % dupes[:5])

    cells = {r["cell"] for r in plan}
    unauthorised = sorted(cells - set(AUTHORISED_CELLS))
    if unauthorised:
        raise PlanError("unauthorised cell(s): %s; only %s are in the contract's "
                        "ISS-06 affected_cells"
                        % (unauthorised, sorted(AUTHORISED_CELLS)))
    if cells != set(AUTHORISED_CELLS):
        raise PlanError("plan is missing cell(s): %s"
                        % sorted(set(AUTHORISED_CELLS) - cells))

    for r in plan:
        expected_scenario = AUTHORISED_CELLS[r["cell"]]
        if r["scenario"] != expected_scenario:
            raise PlanError("scenario %r does not match cell %r (expected %r)"
                            % (r["scenario"], r["cell"], expected_scenario))
        if not r["cell"].startswith(r["scenario"] + "-"):
            raise PlanError("cell %r is not prefixed by scenario %r"
                            % (r["cell"], r["scenario"]))
        if r["identity"] != "%s-s%02d-r0" % (r["cell"], r["seed"]):
            raise PlanError("identity %r does not match cell/seed" % r["identity"])

    for cell in sorted(AUTHORISED_CELLS):
        seeds = [r["seed"] for r in plan if r["cell"] == cell]
        if len(seeds) != len(set(seeds)):
            raise PlanError("cell %s has duplicate seeds" % cell)
        if set(seeds) != REQUIRED_SEEDS:
            missing = sorted(REQUIRED_SEEDS - set(seeds))
            extra = sorted(set(seeds) - REQUIRED_SEEDS)
            raise PlanError("cell %s seed set is not exactly 0..59 "
                            "(missing=%s extra=%s)" % (cell, missing[:5], extra[:5]))
    return plan


# ── output root ────────────────────────────────────────────────────────────
def create_output_root(path):
    """Refuse an existing root; create it atomically."""
    real = os.path.realpath(path)
    if real == OLD_RESULTS or real.startswith(OLD_RESULTS + os.sep):
        raise OutputError("output %r resolves inside the accepted results tree %r"
                          % (real, OLD_RESULTS))
    if os.path.exists(real):
        raise OutputError("output root %r already exists; refusing to reuse or "
                          "merge into it" % real)
    try:
        os.makedirs(real)          # no exist_ok: mkdir is the atomic guard
    except FileExistsError:
        raise OutputError("output root %r was created concurrently" % real)
    return real


def target_paths(out_dir, identity):
    return [os.path.join(out_dir, identity + s) for s in SUFFIXES]


def preflight(out_dir, identity):
    """Nothing is ever overwritten: all three targets must be absent."""
    present = [p for p in target_paths(out_dir, identity) if os.path.exists(p)]
    if present:
        raise OutputError("refusing to overwrite existing output: %s"
                          % [os.path.basename(p) for p in present])


# ── execution ──────────────────────────────────────────────────────────────
def run_one(run, out_dir, inet):
    preflight(out_dir, run["identity"])
    label = "%s-s%02d" % (run["cell"], run["seed"])
    sims = os.path.join(SIM, "simulations")
    cmd = [os.path.relpath(BINARY, sims), "-u", "Cmdenv",
           "-c", run["scenario"], "-f", "lifesat.ini",
           "-n", ".:../src:%s/src" % inet, "-l", "%s/src/libINET.so" % inet,
           "--seed-set=%d" % run["seed"],
           '--*.collector.runLabel="%s"' % label,
           '--*.collector.outputDir="%s"' % os.path.relpath(out_dir, sims)]
    ov = dict(OVERRIDES_D3)
    ov.update(ALWAYS)
    for k, v in sorted(ov.items()):
        cmd.append("--%s=%s" % (k, v))
    p = subprocess.run(cmd, cwd=sims, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("exit %d: %s" % (p.returncode,
                                            (p.stderr or p.stdout)[-400:]))
    digests = {}
    for path in target_paths(out_dir, run["identity"]):
        if not os.path.exists(path):
            raise RuntimeError("%s not produced" % os.path.basename(path))
        digests[os.path.basename(path)] = sha256(path)
    return digests


def execute(plan, out_dir, inet):
    stop = threading.Event()
    completed, failed = [], []
    lock = threading.Lock()

    def work(run):
        if stop.is_set():
            return ("skipped", run, None)
        try:
            return ("ok", run, run_one(run, out_dir, inet))
        except Exception as exc:                     # noqa: BLE001
            stop.set()                               # halt new work immediately
            return ("fail", run, "%s: %s" % (type(exc).__name__, exc))

    with concurrent.futures.ThreadPoolExecutor(MAX_CONCURRENCY) as pool:
        futures = [pool.submit(work, r) for r in plan]
        for fut in concurrent.futures.as_completed(futures):
            status, run, payload = fut.result()
            with lock:
                if status == "ok":
                    completed.append({"identity": run["identity"],
                                      "artefacts": payload})
                elif status == "fail":
                    failed.append({"identity": run["identity"], "error": payload})
    return completed, failed


TEMP_MARKERS = (".tmp", ".part", ".swp", "~")


def expected_artefact_names(plan):
    """The complete set the fleet must produce: 180 identities x 3 files."""
    return {r["identity"] + suf for r in plan for suf in SUFFIXES}


def scan_output_dir(out_dir, plan, allow=()):
    """What is ACTUALLY on disk, classified against what was planned.

    The completed list is what the driver believes it produced. This function
    deliberately does not consult it: a fleet that silently wrote an extra file,
    or whose artefact vanished after the fact, must still be caught.
    """
    expected = expected_artefact_names(plan)
    allowed = set(allow)
    found, stray, temp, dirs = set(), [], [], []
    for entry in sorted(os.listdir(out_dir)):
        path = os.path.join(out_dir, entry)
        if os.path.isdir(path):
            dirs.append(entry)
            continue
        if entry.startswith(".") or entry.endswith(TEMP_MARKERS):
            temp.append(entry)
            continue
        if entry in allowed:
            continue
        if entry in expected:
            found.add(entry)
        else:
            stray.append(entry)

    stems = {}
    for name in found:
        for suf in SUFFIXES:
            if name.endswith(suf):
                stems.setdefault(name[: -len(suf)], []).append(suf)
                break
    incomplete = sorted(k for k, v in stems.items() if len(set(v)) != len(SUFFIXES))
    duplicate_stems = sorted(k for k, v in stems.items() if len(v) != len(set(v)))

    return {"expected_count": len(expected), "found_count": len(found),
            "missing": sorted(expected - found), "stray": sorted(stray),
            "temporary": sorted(temp), "unexpected_directories": sorted(dirs),
            "incomplete_stems": incomplete, "duplicate_stems": duplicate_stems,
            "set_matches_expected_exactly": found == expected}


def audit(plan, out_dir, completed, failed):
    """Filesystem truth first; the completed list is only cross-checked."""
    planned_ids = [r["identity"] for r in plan]
    done_ids = [c["identity"] for c in completed]
    duplicate = sorted({i for i in done_ids if done_ids.count(i) > 1})
    reported_missing = sorted(set(planned_ids) - set(done_ids))
    reported_stray = sorted(set(done_ids) - set(planned_ids))

    fs = scan_output_dir(out_dir, plan)

    counts = {
        "planned": len(planned_ids),
        "expected_artefacts": fs["expected_count"],
        "artefacts_on_disk": fs["found_count"],
        "completed": len(completed),
        "failed": len(failed),
        "duplicate": len(duplicate) + len(fs["duplicate_stems"]),
        "missing": len(set(reported_missing) | set(
            n[: -len(next(s2 for s2 in SUFFIXES if n.endswith(s2)))]
            for n in fs["missing"])),
        "stray": (len(reported_stray) + len(fs["stray"]) + len(fs["temporary"])
                  + len(fs["unexpected_directories"])),
        "incomplete": len(fs["incomplete_stems"]),
    }
    ok = (counts["completed"] == EXPECTED_RUNS and counts["failed"] == 0
          and counts["duplicate"] == 0 and counts["missing"] == 0
          and counts["stray"] == 0 and counts["incomplete"] == 0
          and fs["set_matches_expected_exactly"]
          and counts["artefacts_on_disk"] == EXPECTED_RUNS * len(SUFFIXES))
    detail = {"reported_missing": reported_missing,
              "reported_stray": reported_stray,
              "duplicate_identities": duplicate, "filesystem": fs}
    return counts, detail, ok


def verify_final_tree(out_dir, plan, manifest_name):
    """After the manifest is written the directory must be exactly 540 + 1."""
    fs = scan_output_dir(out_dir, plan, allow=(manifest_name,))
    entries = sorted(os.listdir(out_dir))
    expected_total = EXPECTED_RUNS * len(SUFFIXES) + 1
    ok = (fs["set_matches_expected_exactly"] and not fs["stray"]
          and not fs["temporary"] and not fs["unexpected_directories"]
          and manifest_name in entries and len(entries) == expected_total)
    return {"entries": len(entries), "expected_total": expected_total,
            "manifest_present": manifest_name in entries,
            "artefacts": fs["found_count"], "stray": fs["stray"],
            "temporary": fs["temporary"],
            "unexpected_directories": fs["unexpected_directories"],
            "pass": ok}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="fleet output root; must NOT exist")
    ap.add_argument("--mode", choices=("dry-run", "execute"), default="dry-run")
    ap.add_argument("--inet", default=os.environ.get(
        "INET_ROOT", os.path.expanduser("~/lifesat_workspace/inet-4.7.0")))
    a = ap.parse_args(argv)

    authority = verify_authority()      # BEFORE anything is created
    plan = validate_plan(build_plan())

    if a.mode == "dry-run":
        print(json.dumps({"mode": "dry-run", "output_root": os.path.realpath(a.out),
                          "root_exists_would_refuse": os.path.exists(a.out),
                          "authorised_cells": sorted(AUTHORISED_CELLS),
                          "seeds_per_cell": len(REQUIRED_SEEDS),
                          "authority_verified": True,
                          "contract_version": authority["contract_version"],
                          "src_tree_digest": authority["src_tree_digest"],
                          "planned_runs": len(plan),
                          "expected_artefacts": EXPECTED_RUNS * len(SUFFIXES),
                          "max_concurrency": MAX_CONCURRENCY,
                          "identities": [r["identity"] for r in plan]}, indent=2))
        return 0

    out_dir = create_output_root(a.out)
    started = utc_now()
    completed, failed = execute(plan, out_dir, a.inet)
    counts, detail, ok = audit(plan, out_dir, completed, failed)

    manifest = {
        "schema": "lifesat-rerun-fleet-manifest/v1",
        "issue": "ISS-06", "contract_version": "1.4.3-candidate",
        "started_utc": started, "finished_utc": utc_now(),
        "authority": authority,
        "output_root": out_dir, "max_concurrency": MAX_CONCURRENCY,
        "binary_sha256": sha256(BINARY),
        "twin_cc_sha256": sha256(os.path.join(SIM, "src", "Twin.cc")),
        "ini_sha256": sha256(os.path.join(SIM, "simulations", "lifesat.ini")),
        "driver_sha256": sha256(os.path.abspath(__file__)),
        "planned": [r["identity"] for r in plan],
        "completed": sorted(completed, key=lambda c: c["identity"]),
        "failed": sorted(failed, key=lambda f: f["identity"]),
        "counts": counts, "anomalies": detail,
        "success_criteria": (
            "completed == %d and failed == 0 and duplicate == 0 and missing == 0 "
            "and stray == 0 and the artefact set on disk equals the expected "
            "%d files exactly" % (EXPECTED_RUNS, EXPECTED_RUNS * len(SUFFIXES))),
        "verdict": "GREEN" if ok else "RED",
    }
    manifest_name = "FLEET_MANIFEST.json"
    with open(os.path.join(out_dir, manifest_name), "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    final = verify_final_tree(out_dir, plan, manifest_name)
    manifest["final_tree_check"] = final
    if not final["pass"]:
        manifest["verdict"] = "RED"
        ok = False
    with open(os.path.join(out_dir, manifest_name), "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print(json.dumps({k: manifest[k] for k in
                      ("output_root", "counts", "final_tree_check", "verdict",
                       "binary_sha256")}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    # A refusal is a normal, expected outcome and must read as one: exit 2 with
    # the reason on stderr, never a traceback an operator has to interpret.
    try:
        sys.exit(main())
    except (AuthorityError, PlanError, OutputError) as _exc:
        sys.stderr.write("REFUSED (%s): %s\n" % (type(_exc).__name__, _exc))
        sys.exit(2)

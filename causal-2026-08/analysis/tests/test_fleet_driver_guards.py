#!/usr/bin/env python3
"""Fail-closed guards of analysis/run_rerun_v2.py.

Every test MUTATES a valid fleet plan or output state in exactly one way and
asserts the driver REFUSES it. No simulation is executed: the guards are pure
plan logic plus filesystem checks, so this suite is safe to run at any time.

A guard that merely warns is a defect. Each rejection must raise, and the
message must name the reason, so a silent policy change cannot pass.
"""
import contextlib
import copy
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.dirname(HERE)
SIM = os.path.dirname(ANALYSIS)
sys.path.insert(0, ANALYSIS)

import run_rerun_v2 as D  # noqa: E402


def valid_plan():
    return D.validate_plan(D.build_plan())


@contextlib.contextmanager
def fake_output(plan, subset=None, extra=()):
    """A directory holding the artefact NAMES a fleet would have produced.

    No simulation is run; only the filesystem shape under audit matters.
    """
    root = tempfile.mkdtemp(prefix="lifesat-fleet-fs-")
    try:
        ids = subset if subset is not None else [r["identity"] for r in plan]
        for identity in ids:
            for suf in D.SUFFIXES:
                with open(os.path.join(root, identity + suf), "w") as fh:
                    fh.write("x")
        for name in extra:
            with open(os.path.join(root, name), "w") as fh:
                fh.write("x")
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


class AuthorityPins(unittest.TestCase):
    """A mismatched input must be refused BEFORE anything is created."""

    def test_the_live_tree_matches_every_pin(self):
        info = D.verify_authority()
        self.assertEqual(info["contract_version"], "1.4.3-candidate")
        self.assertEqual(info["src_tree_digest"], D.SRC_TREE_PIN)

    def test_a_wrong_hash_is_refused_and_no_output_root_is_created(self):
        base = tempfile.mkdtemp(prefix="lifesat-fleet-pin-")
        root = os.path.join(base, "fleet")
        original = dict(D.AUTHORITY_PINS)
        D.AUTHORITY_PINS["src/Twin.cc"] = "0" * 64          # wrong pin
        try:
            with self.assertRaises(D.AuthorityError) as cm:
                D.main(["--out", root, "--mode", "execute"])
            self.assertIn("Twin.cc", str(cm.exception))
            self.assertFalse(os.path.exists(root),
                             "the output root was created despite a bad pin")
        finally:
            D.AUTHORITY_PINS.clear()
            D.AUTHORITY_PINS.update(original)
            shutil.rmtree(base, ignore_errors=True)

    def test_a_missing_pinned_file_is_refused(self):
        original = dict(D.AUTHORITY_PINS)
        D.AUTHORITY_PINS["specs/does-not-exist.json"] = "0" * 64
        try:
            with self.assertRaises(D.AuthorityError) as cm:
                D.verify_authority()
            self.assertIn("is missing", str(cm.exception))
        finally:
            D.AUTHORITY_PINS.clear()
            D.AUTHORITY_PINS.update(original)

    def test_a_wrong_seal_digest_is_refused(self):
        original = D.SEAL_PIN
        D.SEAL_PIN = "0" * 64
        try:
            with self.assertRaises(D.AuthorityError) as cm:
                D.verify_authority()
            self.assertIn("seal sha256", str(cm.exception))
        finally:
            D.SEAL_PIN = original

    def test_a_src_tree_change_is_refused_even_if_every_named_file_matches(self):
        original = D.SRC_TREE_PIN
        D.SRC_TREE_PIN = "0" * 64
        try:
            with self.assertRaises(D.AuthorityError) as cm:
                D.verify_authority()
            self.assertIn("src tree digest", str(cm.exception))
        finally:
            D.SRC_TREE_PIN = original


class FilesystemAudit(unittest.TestCase):
    def test_the_expected_set_is_exactly_540_artefacts(self):
        plan = valid_plan()
        self.assertEqual(len(D.expected_artefact_names(plan)), 540)
        self.assertEqual(D.EXPECTED_RUNS * len(D.SUFFIXES), 540)

    def test_a_stray_file_blocks_green_even_when_all_180_completed(self):
        plan = valid_plan()
        completed = [{"identity": r["identity"], "artefacts": {}} for r in plan]
        with fake_output(plan, extra=["A9-D9-s99-r0-events.csv"]) as out:
            counts, detail, ok = D.audit(plan, out, completed, [])
        self.assertFalse(ok, "a stray artefact must block GREEN")
        self.assertGreater(counts["stray"], 0)
        self.assertIn("A9-D9-s99-r0-events.csv", detail["filesystem"]["stray"])

    def test_a_temporary_file_is_stray(self):
        plan = valid_plan()
        completed = [{"identity": r["identity"], "artefacts": {}} for r in plan]
        with fake_output(plan, extra=["A1-D3-s00-r0-events.csv.tmp"]) as out:
            counts, detail, ok = D.audit(plan, out, completed, [])
        self.assertFalse(ok)
        self.assertTrue(detail["filesystem"]["temporary"])

    def test_a_wrong_suffix_is_stray(self):
        plan = valid_plan()
        completed = [{"identity": r["identity"], "artefacts": {}} for r in plan]
        with fake_output(plan, extra=["A1-D3-s00-r0-events.txt"]) as out:
            _c, detail, ok = D.audit(plan, out, completed, [])
        self.assertFalse(ok)
        self.assertIn("A1-D3-s00-r0-events.txt", detail["filesystem"]["stray"])

    def test_an_unexpected_directory_is_stray(self):
        plan = valid_plan()
        completed = [{"identity": r["identity"], "artefacts": {}} for r in plan]
        with fake_output(plan) as out:
            os.mkdir(os.path.join(out, "scratch"))
            counts, detail, ok = D.audit(plan, out, completed, [])
        self.assertFalse(ok)
        self.assertIn("scratch", detail["filesystem"]["unexpected_directories"])

    def test_a_vanished_artefact_is_caught_even_though_the_driver_reported_success(self):
        plan = valid_plan()
        completed = [{"identity": r["identity"], "artefacts": {}} for r in plan]
        with fake_output(plan) as out:
            os.remove(os.path.join(out, "A2-D3-s07-r0-truth.csv"))
            counts, detail, ok = D.audit(plan, out, completed, [])
        self.assertFalse(ok, "the filesystem, not the completed list, is the truth")
        self.assertIn("A2-D3-s07-r0-truth.csv", detail["filesystem"]["missing"])
        self.assertIn("A2-D3-s07-r0", detail["filesystem"]["incomplete_stems"])

    def test_final_tree_must_be_540_artefacts_plus_the_manifest(self):
        plan = valid_plan()
        with fake_output(plan) as out:
            bad = D.verify_final_tree(out, plan, "FLEET_MANIFEST.json")
            self.assertFalse(bad["pass"], "the manifest is absent; must not pass")
            with open(os.path.join(out, "FLEET_MANIFEST.json"), "w") as fh:
                fh.write("{}")
            good = D.verify_final_tree(out, plan, "FLEET_MANIFEST.json")
            self.assertTrue(good["pass"])
            self.assertEqual(good["entries"], 541)
            self.assertEqual(good["expected_total"], 541)
            with open(os.path.join(out, "leftover.log"), "w") as fh:
                fh.write("x")
            self.assertFalse(D.verify_final_tree(
                out, plan, "FLEET_MANIFEST.json")["pass"])


class PlanShape(unittest.TestCase):
    def test_the_fleet_generates_exactly_180_unique_identities(self):
        plan = valid_plan()
        self.assertEqual(len(plan), 180)
        self.assertEqual(len(plan), D.EXPECTED_RUNS)
        self.assertEqual(len({r["identity"] for r in plan}), 180)

    def test_only_the_three_contract_cells_appear(self):
        self.assertEqual({r["cell"] for r in valid_plan()},
                         {"A1-D3", "A2-D3", "A3-D3"})

    def test_every_cell_carries_exactly_seeds_0_to_59(self):
        plan = valid_plan()
        for cell in ("A1-D3", "A2-D3", "A3-D3"):
            seeds = sorted(r["seed"] for r in plan if r["cell"] == cell)
            self.assertEqual(seeds, list(range(60)), cell)

    def test_b0_d3_is_not_reachable_from_the_fleet(self):
        self.assertNotIn("B0-D3", D.AUTHORISED_CELLS)
        self.assertNotIn("B0-D3", {r["cell"] for r in valid_plan()})


class MutationRejections(unittest.TestCase):
    """One mutation each; all six must be refused."""

    def test_M1_existing_output_root_is_refused(self):
        root = tempfile.mkdtemp(prefix="lifesat-fleet-exists-")
        try:
            with self.assertRaises(D.OutputError) as cm:
                D.create_output_root(root)
            self.assertIn("already exists", str(cm.exception))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_M2_duplicate_seed_is_refused(self):
        plan = copy.deepcopy(valid_plan())
        victim = next(r for r in plan if r["cell"] == "A2-D3" and r["seed"] == 41)
        victim["seed"] = 40
        victim["identity"] = "A2-D3-s40-r0"
        with self.assertRaises(D.PlanError) as cm:
            D.validate_plan(plan)
        self.assertIn("duplicate", str(cm.exception).lower())

    def test_M3_missing_seed_is_refused(self):
        plan = [r for r in copy.deepcopy(valid_plan())
                if not (r["cell"] == "A3-D3" and r["seed"] == 17)]
        with self.assertRaises(D.PlanError) as cm:
            D.validate_plan(plan)
        self.assertIn("expected 180", str(cm.exception))

    def test_M3b_missing_seed_with_the_count_restored_is_still_refused(self):
        """A padded plan keeps len == 180, so the count check cannot catch it."""
        plan = copy.deepcopy(valid_plan())
        victim = next(r for r in plan if r["cell"] == "A3-D3" and r["seed"] == 17)
        victim["seed"] = 60                       # outside 0..59
        victim["identity"] = "A3-D3-s60-r0"
        with self.assertRaises(D.PlanError) as cm:
            D.validate_plan(plan)
        self.assertIn("not exactly 0..59", str(cm.exception))

    def test_M4_unauthorised_cell_is_refused(self):
        plan = copy.deepcopy(valid_plan())
        for r in plan:
            if r["cell"] == "A1-D3":
                r["cell"] = "A4-D3"
                r["scenario"] = "A4"
                r["identity"] = "A4-D3-s%02d-r0" % r["seed"]
        with self.assertRaises(D.PlanError) as cm:
            D.validate_plan(plan)
        self.assertIn("unauthorised cell", str(cm.exception))

    def test_M5_scenario_cell_mismatch_is_refused(self):
        plan = copy.deepcopy(valid_plan())
        next(r for r in plan if r["cell"] == "A2-D3")["scenario"] = "A1"
        with self.assertRaises(D.PlanError) as cm:
            D.validate_plan(plan)
        self.assertIn("does not match cell", str(cm.exception))

    def test_M6_pre_existing_output_file_is_refused(self):
        base = tempfile.mkdtemp(prefix="lifesat-fleet-base-")
        root = os.path.join(base, "fleet")
        try:
            D.create_output_root(root)
            identity = "A1-D3-s00-r0"
            D.preflight(root, identity)                       # clean: no raise
            with open(os.path.join(root, identity + "-events.csv"), "w") as fh:
                fh.write("x")
            with self.assertRaises(D.OutputError) as cm:
                D.preflight(root, identity)
            self.assertIn("overwrite", str(cm.exception))
        finally:
            shutil.rmtree(base, ignore_errors=True)


class OutputRootPolicy(unittest.TestCase):
    def test_the_accepted_results_tree_is_never_a_destination(self):
        with self.assertRaises(D.OutputError) as cm:
            D.create_output_root(os.path.join(SIM, "results"))
        self.assertIn("accepted results tree", str(cm.exception))

    def test_a_subdirectory_of_the_accepted_tree_is_also_refused(self):
        with self.assertRaises(D.OutputError):
            D.create_output_root(os.path.join(SIM, "results", "sneaky"))

    def test_a_fresh_root_is_created_atomically_and_then_refuses_reuse(self):
        base = tempfile.mkdtemp(prefix="lifesat-fleet-fresh-")
        root = os.path.join(base, "fleet")
        try:
            self.assertEqual(D.create_output_root(root), os.path.realpath(root))
            self.assertTrue(os.path.isdir(root))
            with self.assertRaises(D.OutputError):
                D.create_output_root(root)        # second call must fail
        finally:
            shutil.rmtree(base, ignore_errors=True)


class StopOnFirstFailure(unittest.TestCase):
    """The first process failure must stop NEW work from being launched.

    run_one is replaced by a fake, so no simulation is executed; what is under
    test is the scheduling policy, not the simulator.
    """

    def test_no_new_work_is_launched_after_the_first_failure(self):
        plan = valid_plan()
        import contextlib as _c
        started = []
        lock = __import__("threading").Lock()
        real = D.run_one

        def fake(run, out_dir, inet):
            with lock:
                started.append(run["identity"])
                first = len(started) == 1
            if first:
                raise RuntimeError("simulated process failure")
            __import__("time").sleep(0.02)
            return {"x": "y"}

        D.run_one = fake
        try:
            completed, failed = D.execute(plan, tempfile.gettempdir(), "/nonexistent")
        finally:
            D.run_one = real

        self.assertEqual(len(failed), 1, "the failure was not recorded")
        self.assertLess(len(started), len(plan),
                        "every run was launched despite an early failure")
        self.assertLessEqual(len(started), 4 * D.MAX_CONCURRENCY,
                             "far more work was launched than the concurrency "
                             "ceiling allows after a stop: %d" % len(started))
        with fake_output(plan, subset=[c["identity"] for c in completed]) as out:
            counts, _detail, ok = D.audit(plan, out, completed, failed)
        self.assertFalse(ok, "a halted fleet must never report success")
        self.assertGreater(counts["missing"], 0)


class SuccessCriteria(unittest.TestCase):
    def test_a_short_fleet_is_not_success(self):
        plan = valid_plan()
        with fake_output(plan) as out:
            completed = [{"identity": r["identity"], "artefacts": {}}
                         for r in plan[:-1]]
            counts, _detail, ok = D.audit(plan, out, completed, [])
        self.assertFalse(ok)
        self.assertEqual(counts["completed"], 179)

    def test_any_failure_is_not_success(self):
        plan = valid_plan()
        with fake_output(plan) as out:
            completed = [{"identity": r["identity"], "artefacts": {}} for r in plan]
            counts, _d, ok = D.audit(plan, out, completed,
                                     [{"identity": "A1-D3-s00-r0", "error": "boom"}])
        self.assertFalse(ok)
        self.assertEqual(counts["failed"], 1)

    def test_a_complete_clean_fleet_is_success(self):
        """The control: without this, every RED above could be RED for free."""
        plan = valid_plan()
        with fake_output(plan) as out:
            completed = [{"identity": r["identity"], "artefacts": {}} for r in plan]
            counts, _d, ok = D.audit(plan, out, completed, [])
        self.assertTrue(ok, "a complete clean fleet must pass the audit")
        self.assertEqual(counts["artefacts_on_disk"], 540)
        self.assertEqual(counts["expected_artefacts"], 540)

    def test_concurrency_ceiling_is_sixteen(self):
        self.assertEqual(D.MAX_CONCURRENCY, 16)


if __name__ == "__main__":
    unittest.main(verbosity=2)

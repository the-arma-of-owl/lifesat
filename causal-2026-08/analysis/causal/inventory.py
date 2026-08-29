#!/usr/bin/env python3
"""inventory.py -- the pilot run set, DERIVED from the accepted contract.

Nothing here is a list somebody typed.  Every identity is enumerated from the
contract's own declarations, so an arm that the contract declares and this
package forgets is impossible: the enumeration is the same object the pilot
gate later reconciles against.

Inferential cells
    pair_intervention_registry.pairs x {attack, fault}
        -> 6 x 2 = 12 cells, one seed each.

Robustness cells
    robustness_spec.arms x pairs x {attack, fault}
        -> 3 x 6 x 2 = 36 cells, one seed each.
    run_id is the exact function robustness_spec.run_id_rule declares:
    RB-{arm_id}-{pair_id}-{arm}-{seed}.  It is parsed back and compared.

Seeds
    The package role is 'pilot', so episode seeds come from
    seed_space_partition['pilot'].  Robustness run seeds are checked against
    seed_space_partition['robustness'] by the accepted validator regardless of
    package role (validate_causal_contract.py, check_robustness), so robustness
    runs take the first robustness seed.  Both are the FIRST seed of their
    space: one seed per cell, no repetition.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import authority  # noqa: E402

ARMS = ("attack", "fault")


def pilot_seed(contract):
    low, _high = contract["precision_and_replication_policy"]["seed_space_partition"]["pilot"]
    return low


def robustness_seed(contract):
    low, _high = \
        contract["precision_and_replication_policy"]["seed_space_partition"]["robustness"]
    return low


def inferential_cells(contract):
    seed = pilot_seed(contract)
    cells = []
    for pair in contract["pair_intervention_registry"]["pairs"]:
        for arm in ARMS:
            cells.append({
                "arm": arm,
                "arm_id": None,
                "kind": "inferential",
                "onset_offset_s": pair["onset_offset_s"],
                "pair_id": pair["pair_id"],
                "run_id": f"{pair['pair_id']}-{arm}-{seed}",
                "run_seed_index": seed,
                "symptom_class": pair["symptom_class"],
                "truth_intervention_class": pair[f"{arm}_arm"]["truth_intervention_class"],
            })
    return cells


def robustness_cells(contract):
    seed = robustness_seed(contract)
    cells = []
    for rb in contract["robustness_spec"]["arms"]:
        for pair in contract["pair_intervention_registry"]["pairs"]:
            for arm in ARMS:
                arm_id = rb["arm_id"]
                cells.append({
                    "arm": arm,
                    "arm_id": arm_id,
                    "generator_id": rb["generator_id"],
                    "kind": "robustness",
                    "onset_offset_s": pair["onset_offset_s"],
                    "pair_id": pair["pair_id"],
                    # robustness_spec.run_id_rule is "RB-{arm_id}-{pair_id}-{arm}-{seed}",
                    # and every declared arm_id ALREADY begins with "RB-", so the rule's
                    # leading RB is that prefix and not a second one. The accepted
                    # parser (generators.parse_robustness_run_id) reads exactly seven
                    # hyphen-separated tokens and rejects a doubled prefix outright.
                    "run_id": f"{arm_id}-{pair['pair_id']}-{arm}-{seed}",
                    "run_seed_index": seed,
                    "symptom_class": pair["symptom_class"],
                    "truth_intervention_class":
                        pair[f"{arm}_arm"]["truth_intervention_class"],
                })
    return cells


def parse_robustness_run_id(run_id, contract=None):
    """Inverse of robustness_spec.run_id_rule, used to prove the forward map.

    Both arm_id ('RB-model-mismatch') and pair_id ('SP-1') contain hyphens, so
    splitting on '-' cannot recover the components on its own.  The contract
    declares BOTH as closed sets, so the inversion resolves them against those
    sets: an id that does not decompose into exactly one declared arm_id and one
    declared pair_id is not a valid robustness run id, which is the property the
    rule is really asserting.
    """
    contract = contract or authority.contract()
    arm_ids = [a["arm_id"] for a in contract["robustness_spec"]["arms"]]
    pair_ids = [p["pair_id"] for p in contract["pair_intervention_registry"]["pairs"]]
    for arm_id in arm_ids:
        for pair_id in pair_ids:
            for arm in ARMS:
                prefix = f"{arm_id}-{pair_id}-{arm}-"
                if run_id.startswith(prefix):
                    tail = run_id[len(prefix):]
                    if tail.isdigit():
                        return {"arm": arm, "arm_id": arm_id, "pair_id": pair_id,
                                "run_seed_index": int(tail)}
    raise ValueError(f"{run_id}: does not decompose into declared components")


def full_inventory(contract=None):
    contract = contract or authority.contract()
    cells = inferential_cells(contract) + robustness_cells(contract)
    seen = {}
    for cell in cells:
        if cell["run_id"] in seen:
            raise ValueError(f"duplicate run_id {cell['run_id']}")
        seen[cell["run_id"]] = cell
    return cells


def expected_identity_set(contract=None):
    return {cell["run_id"] for cell in full_inventory(contract)}


def main():
    contract = authority.contract()
    cells = full_inventory(contract)
    inferential = [c for c in cells if c["kind"] == "inferential"]
    robustness = [c for c in cells if c["kind"] == "robustness"]
    print(f"contract {contract['contract_version']}")
    print(f"pilot seed (episodes)       {pilot_seed(contract)}")
    print(f"pilot seed (robustness)     {robustness_seed(contract)}")
    print(f"inferential cells           {len(inferential)}  "
          f"= {len(contract['pair_intervention_registry']['pairs'])} pairs x 2 arms")
    print(f"robustness cells            {len(robustness)}  "
          f"= {len(contract['robustness_spec']['arms'])} arms x "
          f"{len(contract['pair_intervention_registry']['pairs'])} pairs x 2 arms")
    print(f"TOTAL PILOT RUNS            {len(cells)}")
    print()
    for cell in cells:
        print(f"  {cell['run_id']:<40} {cell['symptom_class']:<28} "
              f"{cell['truth_intervention_class']}")
    # prove the declared run_id function is invertible, as the contract requires
    for cell in robustness:
        back = parse_robustness_run_id(cell["run_id"])
        for key in ("arm", "arm_id", "pair_id", "run_seed_index"):
            if back[key] != cell[key]:
                raise SystemExit(f"run_id {cell['run_id']} does not parse back: "
                                 f"{key} {back[key]!r} != {cell[key]!r}")
    print("\nevery robustness run_id parses back to its own four components")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

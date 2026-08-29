#!/usr/bin/env python3
"""probe_generator_closure.py -- why D-GENERATOR-CLOSURE-01 cannot pass here.

The detector rebuilds each episode's events with `generators.generate_episode`
and requires EXACT equality with the recorded ones.  That is the right rule for
a Phase 2 fixture, where the generator IS the producer.  It cannot hold for
Phase 3, where the producer is the simulation: the generator lays every episode
on a synthetic grid (`contact_start = ordinal * 200000 s`, `base_seq = 4000 +
ordinal * 10`) that no orbital contact schedule can coincide with.

This probe states that as a measurement rather than an opinion.  It takes one
real pilot episode, gives it an id the detector CAN parse an ordinal out of, runs
the detector's own rebuild, and prints both event sets side by side.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ACCEPTED_TOOLS = os.environ.get("LIFESAT_TOOLS", str(Path(__file__).resolve().parents[2] / "tools"))
if not os.path.isdir(ACCEPTED_TOOLS):
    raise SystemExit(
        "the accepted tools package is not present at %s.\n"
        "It is deposited with the run artefacts rather than with the source. "
        "Set LIFESAT_TOOLS to the directory holding causal_core.py."
        % ACCEPTED_TOOLS)
if ACCEPTED_TOOLS not in sys.path:
    sys.path.insert(0, ACCEPTED_TOOLS)

import authority  # noqa: E402
from generators import generate_episode  # noqa: E402
from validate_causal_contract import EPISODE_STRIDE_S  # noqa: E402

PILOT_ROOT = os.environ.get("LIFESAT_PILOT_ROOT", "runs/pilot")
def main():
    contract = authority.contract()
    package = json.load(open(
        os.path.join(PILOT_ROOT, "package", "PHASE3_PILOT_RESULT_PACKAGE.json"),
        encoding="utf-8"))
    events = json.load(open(
        os.path.join(PILOT_ROOT, "authority", "PILOT_raw_event_authority.json"),
        encoding="utf-8"))

    episode = package["episodes"][0]
    recorded = sorted(
        (e for e in events if e["event_id"].rsplit("-E", 1)[0] == episode["episode_id"]),
        key=lambda r: (r["time"], r["event_id"]))

    ordinal = 1
    probe_id = f"PROBE-EP{ordinal:05d}"
    contact_start = ordinal * EPISODE_STRIDE_S
    base_seq = 4000 + ordinal * 10
    rebuilt = generate_episode(contract, episode["pair_id"], episode["arm"],
                               episode["run_seed_index"], probe_id,
                               contact_start, base_seq)

    print(f"episode                : {episode['episode_id']} "
          f"({episode['pair_id']}, {episode['arm']})")
    print(f"detector's rebuild grid: contact_start={contact_start}  "
          f"base_seq={base_seq}")
    print()
    print(f"recorded events (simulation) : {len(recorded)}")
    for row in recorded[:4]:
        print(f"    t={row['time']:<22} {row['category']:<10} {row['fields']}")
    print(f"rebuilt events (generator)   : {len(rebuilt['events'])}")
    for row in rebuilt["events"][:4]:
        print(f"    t={row['time']:<22} {row['category']:<10} {row['fields']}")
    print()
    equal = rebuilt["events"] == recorded
    print(f"exact equality required by D-GENERATOR-CLOSURE-01 : {equal}")
    print()
    print("The two cannot coincide: the generator places the contact at a fixed")
    print("multiple of 200000 s and numbers telemetry from 4000, while the")
    print("simulation's contacts come from SGP4 geometry and its sequence")
    print("numbers from a monotonic onboard counter. The detector is scoped to")
    print("fixtures, where the generator IS the producer. Phase 3 reports this")
    print("rather than renaming episodes to make the check merely fail later.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

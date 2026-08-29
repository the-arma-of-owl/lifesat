#!/usr/bin/env python3
"""probe_sp2_eclipse.py -- is SP-2's onset condition satisfiable at all?

SP-2 is the one pair whose onset carries a physical precondition:

    operational_closure["SP-2"]["attack_arm"]["onset_rule"]
        "the first tm.send at or after contact start + 1200 s, inside eclipse"
    operational_closure["SP-2"]["common_target"]["illumination_rule"]
        "dischargeRate appears ONLY in the eclipse branch ... The intervention
         window must therefore lie wholly inside eclipse"

`dischargeRate` only moves the voltage in the eclipse branch of the step
equation, so an onset in sunlight runs the declared equation with no effect.
This probe measures, over a full 7-day run at the accepted orbit and ground
station, how many CONTACT-VISIBLE telemetry observations were in eclipse.

It reads two recorded outputs and computes nothing of its own:

  * the `illuminated` vector the satellite already records
    (@statistic[illuminated] in CubeSat.ned), and
  * the pass windows from the hash-chained event log.

If the count is zero the pair's onset condition cannot be met in this
configuration, and that is a property of the accepted contract's SP-2 design
against this orbit and ground station -- not of the Phase 3 implementation.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import authority   # noqa: E402
import inventory   # noqa: E402
import rawlog      # noqa: E402
import runcell     # noqa: E402


def read_illuminated(vec_path):
    """The `illuminated` vector, as (time, value) pairs, from the .vec file."""
    vector_id = None
    samples = []
    with open(vec_path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("vector "):
                parts = line.split()
                # vector <id> <module> <name>:vector <columns>
                # OMNeT++ suffixes the recorded name with the record mode, so
                # the bare name never matches and the parse silently yields
                # nothing -- which is how this probe first "concluded" from zero
                # samples. The suffix is stripped rather than assumed absent.
                if len(parts) >= 4 and parts[3].split(":")[0] == "illuminated":
                    vector_id = parts[1]
                continue
            if vector_id is None or not line or not line[0].isdigit():
                continue
            parts = line.split()
            if parts[0] != vector_id or len(parts) < 4:
                continue
            samples.append((float(parts[2]), float(parts[3])))
    return samples


def main():
    contract = authority.contract()
    cell = next(c for c in inventory.full_inventory(contract)
                if c["run_id"] == "SP-2-attack-0")
    workdir = tempfile.mkdtemp(prefix="sp2-eclipse-")
    results = os.path.join(workdir, "results")
    argv, env = runcell.command(cell, workdir, "sp2ecl", contract)
    argv = argv[:1] + [f"--result-dir={results}"] + argv[1:]
    proc = subprocess.run(argv, cwd=runcell.SIM_DIR, env=env,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"probe run failed:\n{proc.stdout[-2000:]}{proc.stderr[-2000:]}")

    events = rawlog.read_events(os.path.join(workdir, "sp2ecl-r0-events.csv"))
    windows = []
    starts = [e["time"] for e in events if e["category"] == "pass.start"]
    ends = [e["time"] for e in events if e["category"] == "pass.end"]
    for start in starts:
        later = [t for t in ends if t >= start]
        if later:
            windows.append((start, min(later)))

    vec = next(os.path.join(results, n) for n in sorted(os.listdir(results))
               if n.endswith(".vec"))
    samples = read_illuminated(vec)
    if not samples:
        raise SystemExit(
            f"no `illuminated` samples were parsed out of {vec}; this probe "
            f"refuses to draw a conclusion from an empty parse")

    def visible(t):
        return any(a <= t <= b for a, b in windows)

    in_contact = [(t, v) for t, v in samples if visible(t)]
    eclipsed = [t for t, v in in_contact if v == 0.0]

    print(f"contacts over 7 days                  : {len(windows)}")
    print(f"illumination samples in total         : {len(samples)}")
    print(f"illumination samples inside a contact : {len(in_contact)}")
    print(f"  ... of which the satellite is in ECLIPSE : {len(eclipsed)}")
    print(f"  ... of which the satellite is SUNLIT     : "
          f"{len(in_contact) - len(eclipsed)}")
    print()
    if not eclipsed:
        print("SP-2's onset condition is UNSATISFIABLE in this configuration:")
        print("over the whole run there is no contact-visible observation with")
        print("the satellite in eclipse, so 'the first tm.send at or after")
        print("contact start + 1200 s, inside eclipse' selects nothing. This is")
        print("a property of the accepted SP-2 design against this orbit, epoch")
        print("and ground station. Phase 3 applies the onset rule literally,")
        print("records that the eclipse condition did not hold, and reports it.")
    else:
        print(f"SP-2's onset condition IS satisfiable: {len(eclipsed)} "
              f"contact-visible eclipsed observations exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

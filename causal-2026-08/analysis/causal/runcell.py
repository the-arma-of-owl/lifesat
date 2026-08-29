#!/usr/bin/env python3
"""runcell.py -- execute ONE pilot cell with the real OMNeT++ executable.

There is no synthetic path here.  If the build is missing, the scenario is not
implemented, or the run exits non-zero, this raises; it never fabricates output.
The run identity is passed on the command line, never hidden in the ini, so the
exact command that produced a raw log is recoverable from the log's own
directory.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True

import authority  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SIM_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SIM_DIR = os.path.join(SIM_ROOT, "simulations")
EXECUTABLE = os.path.join(SIM_ROOT, "lifesat")
CAUSAL_INI = os.path.join(SIM_DIR, "causal.ini")

SIM_TIME_LIMIT = "7d"


class RunError(Exception):
    """A pilot cell did not run."""


def _env():
    """The candidate environment, resolved by sourcing setenv-candidate."""
    script = os.path.join(SIM_ROOT, "setenv-candidate")
    if not os.path.exists(script):
        raise RunError(f"missing {script}")
    proc = subprocess.run(
        ["bash", "-c", f'source "{script}" >/dev/null 2>&1 && env -0'],
        capture_output=True, check=True)
    env = {}
    for item in proc.stdout.split(b"\0"):
        if b"=" in item:
            key, _, value = item.partition(b"=")
            env[key.decode()] = value.decode()
    return env


def scenario_parameters(contract, cell):
    """Every causal number, READ OUT of the accepted contract.

    Nothing below is a literal.  The ini file deliberately carries no
    pair-specific value, so the contract is the only place these can come from
    and a contract revision cannot leave a stale copy behind in a config file.
    """
    pairs = {p["pair_id"]: p for p in contract["pair_intervention_registry"]["pairs"]}
    pair = pairs[cell["pair_id"]]
    closure = contract["operational_closure"]
    nominal = contract["nominal_constants"]
    model = contract["model_authority"]

    # SP-3's ordinal step is declared in the registry as prose; it is parsed
    # rather than retyped, so a change to the registry cannot be ignored here.
    ordinal = re.search(r"([+-]?\d+)\s+ordinal",
                        pairs["SP-3"]["observable_target_schedule"]["target_deviation"])
    if ordinal is None:
        raise RunError("SP-3's ordinal step is not stated in the pair registry")

    params = {
        "arm": cell["arm"],
        "counterTargetDelta": nominal["counter_target_delta"],
        "delayTargetS": nominal["delay_target_s"],
        "durationObservations":
            pair["observable_target_schedule"]["duration_observations"],
        "eclipseSteps": closure["SP-2"]["common_target"]["eclipse_steps"],
        "modeOrdinalDelta": int(ordinal.group(1)),
        "onsetOffsetS": pair["onset_offset_s"],
        "pairId": cell["pair_id"],
        "perturbedDischargeRate":
            closure["SP-2"]["common_target"]["perturbed_discharge_rate_vps"],
        "replayWindowObservations":
            pairs["SP-6"]["observable_target_schedule"]["duration_observations"],
        "robustnessArm": cell["arm_id"] or "",
        "runId": cell["run_id"],
        "runSeedIndex": cell["run_seed_index"],
        "targetDeviationV": abs(closure["SP-1"]["common_target"]["target_deviation_v"]),
        "telemetryIntervalS": model["telemetry_interval_s"],
    }

    magnitude = 0.0
    if cell["arm_id"]:
        arm = next(a for a in contract["robustness_spec"]["arms"]
                   if a["arm_id"] == cell["arm_id"])
        # RB-third-cause declares magnitude null: the perturbation is defined by
        # being unmodelled, not by a size. The injector states its own default
        # and says so; it is not silently borrowed from another arm.
        magnitude = arm["magnitude"] if arm["magnitude"] is not None else 0.0
    params["robustnessMagnitude"] = magnitude
    return params


def defence_overrides(contract, cell):
    """The defence configuration each pair needs, and why.

    Both arms of a pair always get the SAME configuration: an asymmetry here
    would separate the arms by something other than the injection mechanism and
    the matched design would be matched in name only.
    """
    overrides = {}
    if cell["pair_id"] == "SP-5":
        # The SP-5 fault arm's rejections are GENUINE freshness rejections, and
        # the freshness check only runs with command authorisation enabled -- # the contract cites that exact code path (CubeSat.cc:177-180) as this
        # arm's hook. Without D1 there is no rejection to lose.
        overrides["*.sat.commandAuthEnabled"] = "true"
        overrides["*.gs.signCommands"] = "true"
    if cell["arm_id"] == "RB-model-mismatch":
        # robustness_spec: "twin discharge-rate bias, the rateBias already
        # present in the config", magnitude 0.06.
        arm = next(a for a in contract["robustness_spec"]["arms"]
                   if a["arm_id"] == "RB-model-mismatch")
        overrides["*.twin.rateBias"] = repr(arm["magnitude"])
    return overrides


def command(cell, outdir, label, contract=None):
    """The exact argv for one cell.  Returned so the report can quote it."""
    contract = contract or authority.contract()
    env = _env()
    inet = env["INET_ROOT"]
    args = [
        EXECUTABLE, "-u", "Cmdenv", "-c", "Causal",
        "-n", f".:{SIM_ROOT}/src:{inet}/src",
        "-l", f"{inet}/src/libINET.so",
        f"--sim-time-limit={SIM_TIME_LIMIT}",
        f'--*.collector.outputDir="{outdir}"',
        f'--*.collector.runLabel="{label}"',
        f'--*.sat.eclipseSecondsPerOrbit='
        f'{contract["model_authority"]["eclipse_seconds_per_orbit"]}s',
    ]
    # The NED declares these three with @unit(s); a bare number is refused, and
    # that refusal is worth keeping -- it is the type system catching a seconds
    # value handed over without saying it was seconds.
    seconds = {"onsetOffsetS", "delayTargetS", "telemetryIntervalS"}
    for key, value in sorted(scenario_parameters(contract, cell).items()):
        if isinstance(value, str):
            args.append(f'--*.causal.{key}="{value}"')
        elif key in seconds:
            args.append(f"--*.causal.{key}={value!r}s")
        else:
            args.append(f"--*.causal.{key}={value!r}")
    for key, value in sorted(defence_overrides(contract, cell).items()):
        args.append(f"--{key}={value}")
    args.append(f"--seed-set={cell['run_seed_index']}")
    args.append(CAUSAL_INI)
    return args, env


def run(cell, outdir):
    """Runs one cell; returns {label, argv, stdout_tail, files}."""
    if not os.path.exists(EXECUTABLE):
        raise RunError(f"the simulation executable {EXECUTABLE} does not exist; "
                       f"build it before running a pilot cell")
    if not os.path.exists(CAUSAL_INI):
        raise RunError(f"no causal pilot configuration at {CAUSAL_INI}: the "
                       f"deterministic pair injectors are NOT IMPLEMENTED")
    os.makedirs(outdir, exist_ok=True)
    label = cell["run_id"]
    argv, env = command(cell, outdir, label)
    proc = subprocess.run(argv, cwd=SIM_DIR, env=env,
                          capture_output=True, text=True)
    tail = (proc.stdout or "")[-4000:] + (proc.stderr or "")[-4000:]
    if proc.returncode != 0:
        raise RunError(f"{label}: exit {proc.returncode}\n{tail}")
    if "<!> Error" in tail or "Error:" in tail:
        raise RunError(f"{label}: run reported an error\n{tail}")
    events = os.path.join(outdir, f"{label}-r0-events.csv")
    truth = os.path.join(outdir, f"{label}-r0-truth.csv")
    anchor = os.path.join(outdir, f"{label}-r0-anchor.txt")
    for path in (events, truth, anchor):
        if not os.path.exists(path):
            raise RunError(f"{label}: expected artefact {path} was not written")
    return {
        "anchor": anchor,
        "argv": argv,
        "events": events,
        "exit_code": proc.returncode,
        "label": label,
        "stdout_tail": tail[-1500:],
        "truth": truth,
    }


def main():
    import inventory
    contract = authority.contract()
    cells = {c["run_id"]: c for c in inventory.full_inventory(contract)}
    if len(sys.argv) != 3:
        print("usage: runcell.py <run_id> <outdir>", file=sys.stderr)
        return 2
    run_id, outdir = sys.argv[1], sys.argv[2]
    if run_id not in cells:
        print(f"unknown run_id {run_id}", file=sys.stderr)
        return 2
    result = run(cells[run_id], outdir)
    print(" ".join(result["argv"]))
    print(f"wrote {result['events']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

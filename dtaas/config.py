"""LIFESAT DTaaS -- pinned paths and catalog.

Binding rules:
  1. Results are a deployment demonstration; they are not compared with the accepted run fleets.
  2. No output writes into the accepted trees -- every instance writes to its own directory.
  3. The service refuses to start unless the code tree matches the identity the
     operator pinned. Both halves of that identity are supplied by the deployment,
     because the repository does not know which revision an operator deployed.

The reported deployment demonstration ran on the post-experiment hardened tree,
tagged v1.1.0, which is a successor of the frozen producer published here.
"""
import os
from pathlib import Path


def _env_path(name: str, default: Path) -> Path:
    """Use the environment variable if set, otherwise the default.

    Paths on a deployment machine differ (e.g. a cloud VM). Rather than keeping two
    versions of the code, the paths can be supplied externally; the defaults are the
    development machine's paths and are unchanged.
    """
    v = os.environ.get(name)
    return Path(v).expanduser().resolve() if v else default


ROOT = Path(__file__).resolve().parent
CODE = _env_path("LIFESAT_CODE", ROOT.parent / "matrix-2026-07")
SIMS = CODE / "simulations"
BIN = CODE / "out" / "clang-release" / "lifesat"
INSTANCES = _env_path("LIFESAT_INSTANCES", ROOT / "instances")

OMNETPP_ROOT = _env_path("OMNETPP_ROOT", Path(os.environ.get("LIFESAT_EXT_REF", "")))
INET_ROOT = _env_path("INET_ROOT", Path(os.environ.get("LIFESAT_EXT_REF", "")))

# named configurations in lifesat.ini
SCENARIOS = ["B0", "A1", "A2", "A3", "A4"]
DEFENCES = ["D0", "D1", "D2", "D3"]

# identical to analysis/run_matrix.py (OVERRIDES/ALWAYS)
ALWAYS = {"*.rnd.enabled": "true"}
OVERRIDES = {
    "D0": {"*.sat.commandAuthEnabled": "false", "*.gs.signCommands": "false",
           "*.flow.enabled": "false", "*.twin.enabled": "false"},
    "D1": {"*.sat.commandAuthEnabled": "true", "*.gs.signCommands": "true",
           "*.flow.enabled": "false", "*.twin.enabled": "false"},
    # the D2 threshold file is required: FlowDetector refuses to run uncalibrated.
    # thresholdFile is added per instance in instance.py.
    "D2": {"*.sat.commandAuthEnabled": "true", "*.gs.signCommands": "true",
           "*.flow.enabled": "true", "*.twin.enabled": "false",
           "*.flow.windowSize": "60s"},
    "D3": {"*.sat.commandAuthEnabled": "true", "*.gs.signCommands": "true",
           "*.flow.enabled": "false", "*.twin.enabled": "true"},
}

# calibration artefact -- actual location in the accepted tree
D2_THRESHOLDS = CODE / "results" / "d2_thresholds.txt"

# Version pinning: the service starts only under the identity the operator pinned.
# Both halves come from the deployment. A revision hard-coded here would either be
# wrong for every other clone or would have to be edited before each deployment,
# and an unpinned service would silently run whatever happened to be checked out.
EXPECTED_GIT_COMMIT = os.environ.get("LIFESAT_EXPECTED_COMMIT", "")

# The binary digest depends on the compiler and the machine: the same commit produces
# different bytes elsewhere.
EXPECTED_BIN_SHA256 = os.environ.get("LIFESAT_EXPECTED_BIN", "")

# Free-form label echoed back in the identity response, for the operator's own
# records. It is not checked against anything.
EXPECTED_TAG = os.environ.get("LIFESAT_EXPECTED_TAG", "")

# fail-closed resource limits
MAX_ACTIVE_INSTANCES = 4
MAX_REGISTRY = 64
MAX_BODY_BYTES = 8192
INSTANCE_TTL_S = 3600

DEFAULT_HORIZON = 604800.0   # 7 days, the run_matrix --end default
MAX_HORIZON = 604800.0

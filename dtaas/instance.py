"""On-demand setup, execution and teardown of a twin instance.

Containment: every instance writes only to its own directory.
  - `--*.collector.outputDir` is redirected into the instance directory
  - `--result-dir` is redirected into the instance directory
  - vector/scalar recording is switched off (no repeat of the 47 MB leak)
"""
import hashlib, json, os, shlex, shutil, subprocess, time, uuid
from pathlib import Path
import config as C


class BadRequest(ValueError):
    pass


#: States where teardown is refused and capacity is counted. provisioned is included:
#: a DELETE arriving between provision() and run() could remove the directory and leave
#: the worker in a deleted one.
ACTIVE_STATES = ("provisioning", "provisioned", "running", "scoring")


def verify_code_identity():
    """The service starts only on the pinned code identity. Raises on a mismatch."""
    import subprocess as sp
    if not C.EXPECTED_GIT_COMMIT or not C.EXPECTED_BIN_SHA256:
        raise RuntimeError(
            "no code identity pinned: set LIFESAT_EXPECTED_COMMIT and "
            "LIFESAT_EXPECTED_BIN to the revision and binary digest being deployed")
    r = sp.run(["git", "rev-parse", "HEAD"], cwd=str(C.CODE),
               capture_output=True, text=True)
    commit = r.stdout.strip()
    if r.returncode != 0 or commit != C.EXPECTED_GIT_COMMIT:
        raise RuntimeError(f"code tree commit {commit or '<unknown>'} != pinned {C.EXPECTED_GIT_COMMIT}")
    dirty = sp.run(["git", "status", "--porcelain"], cwd=str(C.CODE),
                   capture_output=True, text=True).stdout.strip()
    if dirty:
        raise RuntimeError(f"code tree has uncommitted changes:\n{dirty[:400]}")
    if not C.BIN.exists():
        raise RuntimeError(f"binary missing: {C.BIN}")
    digest = hashlib.sha256(C.BIN.read_bytes()).hexdigest()
    if digest != C.EXPECTED_BIN_SHA256:
        raise RuntimeError(f"binary sha256 {digest} != pinned {C.EXPECTED_BIN_SHA256}")
    return {"git_commit": commit, "binary_sha256": digest,
            "tag": C.EXPECTED_TAG}


def validate(req: dict) -> dict:
    if not isinstance(req, dict):
        raise BadRequest("body must be a JSON object")
    sc = req.get("scenario")
    de = req.get("defence")
    if sc not in C.SCENARIOS:
        raise BadRequest(f"scenario must be one of {C.SCENARIOS}")
    if de not in C.DEFENCES:
        raise BadRequest(f"defence must be one of {C.DEFENCES}")
    seed = req.get("seed", 0)
    if not isinstance(seed, int) or not 0 <= seed < 1000:
        raise BadRequest("seed must be an integer in [0,1000)")
    hz = float(req.get("horizon", C.DEFAULT_HORIZON))
    if not 0 < hz <= C.MAX_HORIZON:
        raise BadRequest(f"horizon must be in (0,{C.MAX_HORIZON}]")
    sat = req.get("satellite", "FUNCUBE-1")
    if sat != "FUNCUBE-1":
        # lifesat.ini is pinned to a single TLE; accepting another satellite name would
        # report a configuration that never ran.
        raise BadRequest("satellite must be 'FUNCUBE-1' (the only configured TLE)")
    return {"satellite": sat, "scenario": sc, "defence": de,
            "seed": seed, "horizon": hz}


def build_argv(spec: dict, workdir: Path) -> list:
    """The same call as run_matrix.run_cell plus the containment redirections."""
    label = f"{spec['scenario']}-{spec['defence']}-s{spec['seed']:02d}"
    inet = str(C.INET_ROOT)
    argv = [str(C.BIN), "-u", "Cmdenv", "-c", spec["scenario"],
            "-f", str(C.SIMS / "lifesat.ini"),
            "-n", f"{C.SIMS}:{C.CODE/'src'}:{inet}/src",
            "-l", f"{inet}/src/libINET.so",
            f"--seed-set={spec['seed']}",
            f'--*.collector.runLabel="{label}"']
    ov = dict(C.OVERRIDES[spec["defence"]]); ov.update(C.ALWAYS)
    if spec["defence"] == "D2":
        # FlowDetector refuses to run uncalibrated; the path must point at the artefact
        # copied into the instance directory (quoted because it is a string).
        ov["*.flow.thresholdFile"] = f'"{workdir / "results" / C.D2_THRESHOLDS.name}"'
    for k, v in sorted(ov.items()):
        argv.append(f"--{k}={v}")
    # --- containment ---
    argv += [f'--*.collector.outputDir="{workdir/"results"}"',
             f"--result-dir={workdir/'omnetpp-native'}",
             "--**.vector-recording=false",
             "--**.scalar-recording=false",
             f"--sim-time-limit={spec['horizon']}s"]
    return argv


def config_digest(spec: dict, argv: list) -> str:
    blob = json.dumps({"spec": spec, "argv": argv}, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


class Instance:
    def __init__(self, spec: dict):
        self.id = uuid.uuid4().hex[:16]
        self.spec = spec
        self.dir = C.INSTANCES / self.id
        self.status = "provisioning"
        self.error = None
        self.result = None
        self.provisioning_time_s = None
        self.run_time_s = None
        self.argv = None
        self.config_sha256 = None
        self.created = time.time()

    # -- setup: isolated workspace --
    def provision(self):
        t0 = time.time()
        (self.dir / "results").mkdir(parents=True, exist_ok=True)
        (self.dir / "omnetpp-native").mkdir(exist_ok=True)
        # D2 calibration artefact, from its actual location in the accepted tree
        if self.spec["defence"] == "D2":
            if not C.D2_THRESHOLDS.exists():
                raise RuntimeError(f"D2 calibration artefact missing: {C.D2_THRESHOLDS}")
            shutil.copy2(C.D2_THRESHOLDS, self.dir / "results" / C.D2_THRESHOLDS.name)
        self.argv = build_argv(self.spec, self.dir)
        self.config_sha256 = config_digest(self.spec, self.argv)
        self.provisioning_time_s = round(time.time() - t0, 4)
        self.status = "provisioned"

    # -- execution: pinned environment --
    def run(self, timeout=3600):
        self.status = "running"
        t0 = time.time()
        quoted = " ".join(shlex.quote(a) for a in self.argv)
        script = (f"export OMNETPP_ROOT='{C.OMNETPP_ROOT}'; "
                  f"export INET_ROOT='{C.INET_ROOT}'; "
                  f"source '{C.CODE}/setenv' >/dev/null 2>&1; "
                  f"exec {quoted}")
        try:
            p = subprocess.run(["bash", "-lc", script], cwd=str(self.dir),
                               capture_output=True, text=True, timeout=timeout)
            self.run_time_s = round(time.time() - t0, 3)
            (self.dir / "stdout.txt").write_text(p.stdout[-40000:])
            (self.dir / "stderr.txt").write_text(p.stderr[-40000:])
            if p.returncode != 0:
                self.status = "failed"
                self.error = f"exit {p.returncode}: {p.stderr.strip()[-400:]}"
                return
        except subprocess.TimeoutExpired:
            self.run_time_s = round(time.time() - t0, 3)
            self.status = "failed"; self.error = "timeout"
            return
        self.status = "scoring"
        self._score()

    def _score(self):
        res = self.dir / "results"
        label = f"{self.spec['scenario']}-{self.spec['defence']}-s{self.spec['seed']:02d}"
        ev = sorted(res.glob(f"{label}-*-events.csv")) or sorted(res.glob("*-events.csv"))
        tr = sorted(res.glob(f"{label}-*-truth.csv")) or sorted(res.glob("*-truth.csv"))
        if len(ev) != 1:
            self.status = "failed"
            self.error = f"expected exactly one event record for {label}, found {len(ev)}"
            return
        if len(tr) > 1:
            self.status = "failed"
            self.error = f"expected at most one truth record for {label}, found {len(tr)}"
            return
        cmd = ["python3", "-B", str(C.CODE / "analysis" / "score.py"), str(ev[0]),
               "--json", "--end", str(self.spec["horizon"])]
        if tr:
            cmd += ["--truth", str(tr[0])]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=str(C.CODE / "analysis"), env=env)
        if p.returncode != 0:
            self.status = "failed"
            self.error = f"scorer exit {p.returncode}: {p.stderr.strip()[-300:]}"
            return
        try:
            self.result = json.loads(p.stdout)
        except json.JSONDecodeError:
            self.result = {"raw": p.stdout[-4000:]}
        self.event_record_sha256 = hashlib.sha256(ev[0].read_bytes()).hexdigest()
        self.status = "done"

    def teardown(self):
        """A running instance cannot be torn down; interrupting it causes data loss and a state race."""
        if self.status in ACTIVE_STATES:
            raise BadRequest(f"instance is {self.status}; wait for completion before deletion")
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.status = "destroyed"

    def discard(self):
        """Unconditional cleanup -- for rolling back a failed setup only."""
        if self.dir.exists():
            shutil.rmtree(self.dir, ignore_errors=True)

    def view(self, full=False):
        d = {"instance_id": self.id, "status": self.status, "spec": self.spec,
             "provisioning_time_s": self.provisioning_time_s,
             "run_time_s": self.run_time_s,
             "config_sha256": self.config_sha256,
             "disposition": "deployment demonstration; not comparable to the accepted 1,404-run fleet"}
        if self.error:
            d["error"] = self.error
        if full:
            d["scored_result"] = self.result
            d["event_record_sha256"] = getattr(self, "event_record_sha256", None)
        return d

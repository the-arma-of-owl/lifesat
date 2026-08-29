"""LIFESAT DTaaS -- on-demand twin instantiation service.

Endpoints
  GET    /health           liveness
  GET    /catalog          the set of scenarios/defences that may be requested
  POST   /twins            request an instance  {satellite,scenario,defence,seed,horizon}
  GET    /twins            list instances
  GET    /twins/{id}       status
  GET    /twins/{id}/result  scored result
  DELETE /twins/{id}       tear down

Uses the standard library only; no extra dependency is needed on the cloud VM.
"""
import json, threading, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import config as C
from instance import Instance, validate, BadRequest, verify_code_identity, ACTIVE_STATES

REG = {}
LOCK = threading.Lock()
IDENTITY = {}


def _worker(inst):
    try:
        inst.provision()
    except Exception as e:                       # noqa: BLE001
        inst.status = "failed"; inst.error = repr(e)
        inst.discard()                           # roll back the half-built instance
        return
    try:
        inst.run()
    except Exception as e:                       # noqa: BLE001
        inst.status = "failed"; inst.error = repr(e)


def _reap():
    """Collect expired completed instances from both the registry and the disk."""
    now = time.time()
    with LOCK:
        stale = [REG.pop(i) for i, x in list(REG.items())
                 if x.status in ("done", "failed") and now - x.created > C.INSTANCE_TTL_S]
    for inst in stale:                       # disk cleanup outside the lock
        inst.discard()


class H(BaseHTTPRequestHandler):
    server_version = "LIFESAT-DTaaS/1.0"

    def _send(self, code, obj):
        b = json.dumps(obj, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def log_message(self, fmt, *a):
        sys.stderr.write("  %s\n" % (fmt % a))

    # ---------- GET ----------
    def do_GET(self):
        p = self.path.rstrip("/")
        if p in ("", "/health"):
            return self._send(200, {"status": "ok", "service": "LIFESAT DTaaS",
                                    "code_identity": IDENTITY,
                                    "active": sum(1 for x in REG.values() if x.status in ACTIVE_STATES)})
        if p == "/catalog":
            return self._send(200, {"scenarios": C.SCENARIOS, "defences": C.DEFENCES,
                                    "default_horizon_s": C.DEFAULT_HORIZON,
                                    "note": "results are a deployment demonstration, "
                                            "not new scientific evidence"})
        if p == "/twins":
            with LOCK:
                return self._send(200, {"instances": [i.view() for i in REG.values()]})
        parts = p.split("/")
        if len(parts) >= 3 and parts[1] == "twins":
            inst = REG.get(parts[2])
            if not inst:
                return self._send(404, {"error": "no such instance"})
            if len(parts) == 4 and parts[3] == "result":
                if inst.status != "done":
                    return self._send(409, {"error": "not ready", "status": inst.status})
                return self._send(200, inst.view(full=True))
            return self._send(200, inst.view())
        self._send(404, {"error": "unknown endpoint"})

    # ---------- POST ----------
    def do_POST(self):
        if self.path.rstrip("/") != "/twins":
            return self._send(404, {"error": "unknown endpoint"})
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self._send(400, {"error": "bad Content-Length"})
        if n < 0 or n > C.MAX_BODY_BYTES:
            return self._send(413, {"error": f"body must be at most {C.MAX_BODY_BYTES} bytes"})
        _reap()
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            spec = validate(req)
        except BadRequest as e:
            return self._send(400, {"error": str(e)})
        except json.JSONDecodeError:
            return self._send(400, {"error": "body must be JSON"})
        # capacity check and slot reservation happen in one locked region; splitting them
        # would let a burst of concurrent POSTs cross the limit together.
        inst = Instance(spec)
        with LOCK:
            active = sum(1 for x in REG.values() if x.status in ACTIVE_STATES)
            if active >= C.MAX_ACTIVE_INSTANCES:
                return self._send(429, {"error": f"at most {C.MAX_ACTIVE_INSTANCES} concurrent instances"})
            if len(REG) >= C.MAX_REGISTRY:
                return self._send(429, {"error": f"registry full ({C.MAX_REGISTRY}); delete finished instances"})
            REG[inst.id] = inst                  # the slot is reserved under the same lock
        threading.Thread(target=_worker, args=(inst,), daemon=True).start()
        self._send(202, inst.view())

    # ---------- DELETE ----------
    def do_DELETE(self):
        parts = self.path.rstrip("/").split("/")
        if len(parts) != 3 or parts[1] != "twins":
            return self._send(404, {"error": "unknown endpoint"})
        with LOCK:
            inst = REG.pop(parts[2], None)
        if not inst:
            return self._send(404, {"error": "no such instance"})
        try:
            inst.teardown()
        except BadRequest as e:
            with LOCK: REG[inst.id] = inst          # put it back
            return self._send(409, {"error": str(e), "status": inst.status})
        self._send(200, {"instance_id": inst.id, "status": "destroyed"})


def main(port=8873):
    global IDENTITY
    IDENTITY = verify_code_identity()          # does not start on a mismatch
    print("  code identity verified:", IDENTITY["git_commit"][:12], IDENTITY["tag"])
    C.INSTANCES.mkdir(parents=True, exist_ok=True)
    print(f"LIFESAT DTaaS  http://127.0.0.1:{port}")
    print(f"  kod      : {C.CODE}")
    print(f"  instances: {C.INSTANCES}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8873)

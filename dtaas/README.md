# Twin instantiation service

A prototype HTTP interface that instantiates a twin on request, runs one scored
scenario, returns the outcome and the event-record digest, and discards the
instance.

## Scope

Single-tenant, bound to `127.0.0.1`, unauthenticated. It demonstrates on-demand
instantiation and containment, not the multi-tenancy or elasticity a hosted
service would need. Every response is labelled a deployment demonstration and is
not comparable to the accepted run fleets.

## Run

```bash
export LIFESAT_CODE=/path/to/causal-2026-08
export OMNETPP_ROOT=/path/to/omnetpp-6.4.0
export INET_ROOT=/path/to/inet-4.7.0
export LIFESAT_EXPECTED_COMMIT=<the revision you are deploying>
export LIFESAT_EXPECTED_TAG=<optional label for your own records>
export LIFESAT_EXPECTED_BIN=<sha256 of your built binary>

python3 -B service.py            # listens on 127.0.0.1:8873
python3 -B smoke_test.py         # 22 checks
```

The binary digest depends on the compiler and the machine, so the same commit
produces different bytes elsewhere. The git commit is universal, the binary
digest is not.

## Endpoints

| | |
|---|---|
| `GET /health` | status and verified code identity |
| `GET /catalog` | scenarios, defences, default horizon |
| `POST /twins` | instantiate; body selects scenario, defence, seed |
| `GET /twins/{id}` | instance state |
| `GET /twins/{id}/result` | scored outcome, once complete |
| `DELETE /twins/{id}` | teardown |

## Guarantees

Before admitting work the service verifies the pinned git commit, a clean
working tree and the binary digest, and refuses to run on a mismatch. Each
instance writes only into its own directory; nothing is written into the
accepted result trees. Capacity is checked and the slot reserved inside one
locked region, so a burst of concurrent requests cannot cross the limit
together.

Limits: 4 concurrent instances, 64 registry entries, 8 KiB request body,
3600 s instance lifetime.

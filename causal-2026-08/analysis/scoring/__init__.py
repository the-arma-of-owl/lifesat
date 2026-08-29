"""LIFESAT contract-conformant scoring package.

Implements the accepted scoring contract (lifesat-scoring-contract/v1,
version 1.4.1-candidate, sealed 2026-08-11T00:44:57Z). The package is layered so
that each contract concern lives in one module:

    artefacts  - run artefacts, join policy, fail-closed scope rules
    ontology   - raw-event mapping, attack identity, provenance separation
    matching   - action-to-outcome matching policy (no global time constant)
    state      - parameter-store reconstruction, idempotency, effect windows
    windows    - observation / expected-arrival windows, D2 decision sets
    metrics    - count-form F-scores, undefined and qualifier codes
    families   - F0..F4 result families
    output     - contract output schema, cells, provenance, per-run records
"""

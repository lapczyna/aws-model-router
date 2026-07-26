# Unit tests

Fast, isolated tests with no I/O — no filesystem, network, or AWS dependency (except the
`adapters/config/` suite, which deliberately exercises real, local file reads against
fixtures in `tests/fixtures/config/` — still no network or AWS credentials).

* `domain/` — domain models, reason-code ordering, requirements merging, candidate
  filtering, routing strategies, cost/token estimation.
* `application/` — `RouteEvaluationService` end-to-end, using the in-memory fakes in
  `tests/support/fakes.py`.
* `adapters/config/` — the local YAML/JSON-backed `ModelCatalogue` and
  `RoutingPolicyRepository` implementations.
* `shared/` — `SystemClock` and `Uuid4IdentifierGenerator`.

Run with `pytest -m unit`, or simply `pytest` / `make test` for the full suite.

# Unit tests

Fast, isolated tests with no I/O — no filesystem, network, or AWS dependency. These test
`src/domain/` and `src/application/` logic directly.

Test files added starting in Phase 2. Run with `pytest -m unit` once markers are applied,
or simply `pytest` / `make test` to run the full suite.

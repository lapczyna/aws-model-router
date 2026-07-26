# Integration tests

Tests exercising multiple in-process components together (e.g. policy resolution +
candidate filtering + cost evaluation + routing strategy end-to-end), still without any
live AWS dependency.

Test files added starting in Phase 2/4. Live-AWS smoke tests are a separate, explicitly
opt-in category introduced in Phase 3 — they do not live here and are excluded from CI.

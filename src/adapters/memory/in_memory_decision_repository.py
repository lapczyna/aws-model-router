import threading

from domain.invocation import AuditRecord


class InMemoryRoutingDecisionRepository:
    """Thread-safe, single-process `domain.ports.RoutingDecisionRepository` implementation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, AuditRecord] = {}

    def save(self, audit_record: AuditRecord) -> None:
        with self._lock:
            self._records[audit_record.decision.decision_id] = audit_record

    def get(self, decision_id: str) -> AuditRecord | None:
        with self._lock:
            return self._records.get(decision_id)

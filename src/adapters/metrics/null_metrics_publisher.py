from domain.invocation import InferenceResult


class NullMetricsPublisher:
    """A `domain.ports.MetricsPublisher` that discards everything.

    `InvocationOrchestrator`'s `metrics_publisher` parameter already defaults to `None`
    and skips publishing entirely, so this is never required there — it exists for
    call sites that want an always-present collaborator (e.g. a fixed-arity test
    fixture) without special-casing `None`.
    """

    def publish(self, result: InferenceResult) -> None:
        return None

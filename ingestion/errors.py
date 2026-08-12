"""The one error type ingestion raises on its own behalf."""


class IngestionError(RuntimeError):
    """A document cannot be ingested correctly, so the run stops.

    Raised where a quiet degradation would ship a wrong citation: an unresolvable
    page, a missing body marker, a document whose identity cannot be established.
    """

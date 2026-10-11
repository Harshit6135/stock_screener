"""Domain errors that adapters can translate into API or CLI responses."""


class DomainValidationError(ValueError):
    """Raised when a framework-independent domain invariant is violated."""

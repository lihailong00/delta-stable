"""Project-specific exceptions."""


class ArbError(Exception):
    """Base exception for the project."""


class ConfigError(ArbError):
    """Raised when runtime configuration is invalid."""


class ExchangeError(ArbError):
    """Raised for exchange API failures."""


class ValidationError(ArbError):
    """Raised when inbound/outbound data is invalid."""

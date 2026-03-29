class ProviderConfigurationError(RuntimeError):
    """Raised when a required external provider is not configured."""


class ProviderRequestError(RuntimeError):
    """Raised when a required external provider call fails."""


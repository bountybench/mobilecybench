class TokenTrackingError(Exception):
    """Base exception for all token tracking errors."""

    pass


class ModelPricingNotFoundError(TokenTrackingError):
    """Raised when no pricing information is found for a given model.

    Non-critical error - continue with all prices set to $0.0. Token Count is still tracked.
    """

    pass


class UnsupportedProviderError(TokenTrackingError):
    """Raised when an unsupported provider is specified.

    Critical error - entire token tracking should be skipped.
    """

    pass


class UsageNotFoundError(TokenTrackingError):
    """Raised when there is no usage field from a response.

    Critical error - entire token tracking should be skipped.
    """

    pass


class ExtractorNotConfiguredError(TokenTrackingError):
    """Raised when no extractor is configured for a provider.

    Critical error - entire token tracking should be skipped.
    """

    pass


class CalculatorNotConfiguredError(TokenTrackingError):
    """Raised when no pricing calculator is configured for a provider.

    Non-critical error - continue with all prices set to $0.0. Token Count is still tracked.
    """

    pass

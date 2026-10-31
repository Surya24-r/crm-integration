from app.zoho_client import ZohoError


class DataError(ZohoError):
    """Permanent problem with the data (unmapped product, no products, ...).
    Fix it, then use the retry button."""

    def __init__(self, message: str):
        super().__init__(message, retryable=False)
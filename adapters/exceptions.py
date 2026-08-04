class SupplierError(Exception):
    """Base exception for all normalized supplier errors."""
    def __init__(self, message: str, supplier_id: str, original_error: Exception | None = None):
        super().__init__(message)
        self.message = message
        self.supplier_id = supplier_id
        self.original_error = original_error

    def __str__(self) -> str:
        return f"[{self.supplier_id.upper()}] {self.message}"


class SupplierTimeoutError(SupplierError):
    """Raised when a supplier request times out."""
    pass


class SupplierServerError(SupplierError):
    """Raised when a supplier returns a 5xx server error."""
    pass


class SupplierMalformedResponseError(SupplierError):
    """Raised when a supplier returns invalid, incomplete, or unexpected response format."""
    pass


class SupplierPriceChangedError(SupplierError):
    """Raised when property re-check reveals a price change from original offer."""
    def __init__(self, message: str, supplier_id: str, old_price: float, new_price: float, original_error: Exception | None = None):
        super().__init__(message, supplier_id, original_error)
        self.old_price = old_price
        self.new_price = new_price


class SupplierNotFoundError(SupplierError):
    """Raised when a requested property or reservation is not found."""
    pass


class SupplierBookingError(SupplierError):
    """Raised when a reservation creation or cancellation fails."""
    pass

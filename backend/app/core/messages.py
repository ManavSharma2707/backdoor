"""Default user facing messages for API errors.

Rules are in `ui-copywriting.md`: plain, no long dashes, say what to do next, never blame the
person. Endpoints raise `AppError` with a more specific message when they have one.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    IDEMPOTENCY_MISMATCH = "IDEMPOTENCY_MISMATCH"
    RATE_LIMITED = "RATE_LIMITED"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    BATCH_EXPIRED = "BATCH_EXPIRED"
    RECEIPT_EXCEEDS_ORDER = "RECEIPT_EXCEEDS_ORDER"
    RETURN_EXCEEDS_SOLD = "RETURN_EXCEEDS_SOLD"
    PO_STATE_INVALID = "PO_STATE_INVALID"
    REPORT_NOT_READY = "REPORT_NOT_READY"
    MISSING_SUPPLIER_OR_COST = "MISSING_SUPPLIER_OR_COST"
    AGENTS_DISABLED = "AGENTS_DISABLED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    INTERNAL = "INTERNAL"


STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.CONFLICT: 409,
    ErrorCode.IDEMPOTENCY_MISMATCH: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.INSUFFICIENT_STOCK: 409,
    ErrorCode.BATCH_EXPIRED: 409,
    ErrorCode.RECEIPT_EXCEEDS_ORDER: 409,
    ErrorCode.RETURN_EXCEEDS_SOLD: 409,
    ErrorCode.PO_STATE_INVALID: 409,
    ErrorCode.REPORT_NOT_READY: 409,
    ErrorCode.MISSING_SUPPLIER_OR_COST: 409,
    ErrorCode.AGENTS_DISABLED: 503,
    ErrorCode.QUOTA_EXHAUSTED: 503,
    ErrorCode.INTERNAL: 500,
}

DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_ERROR: "Some fields need attention. Check them and try again.",
    ErrorCode.UNAUTHENTICATED: "You were signed out. Sign in to continue.",
    ErrorCode.FORBIDDEN: "You do not have access to this.",
    ErrorCode.NOT_FOUND: "We could not find that.",
    ErrorCode.METHOD_NOT_ALLOWED: "That action is not available here.",
    ErrorCode.CONFLICT: "That conflicts with what is already saved. Reload and try again.",
    ErrorCode.IDEMPOTENCY_MISMATCH: "That request key was already used with different details.",
    ErrorCode.RATE_LIMITED: "Too many requests. Wait a moment and try again.",
    ErrorCode.INSUFFICIENT_STOCK: "There is not enough stock. Lower the quantity or record a delivery first.",
    ErrorCode.BATCH_EXPIRED: "That batch has expired and cannot be sold.",
    ErrorCode.RECEIPT_EXCEEDS_ORDER: "That is more than the open quantity on this order. Mark it as an exception to receive more.",
    ErrorCode.RETURN_EXCEEDS_SOLD: "You cannot return more than was sold.",
    ErrorCode.PO_STATE_INVALID: "This order cannot be changed in its current state.",
    ErrorCode.REPORT_NOT_READY: "The plan is not ready yet. Try again in a minute.",
    ErrorCode.MISSING_SUPPLIER_OR_COST: "Add a supplier and a cost for this product first.",
    ErrorCode.AGENTS_DISABLED: "The assistant is switched off. You can still read the reason on each line.",
    ErrorCode.QUOTA_EXHAUSTED: "The assistant is busy right now. Try again in a minute. You can still read the reason on each line.",
    ErrorCode.INTERNAL: "Something went wrong on our side. Try again. If it keeps happening, tell us the time it happened.",
}

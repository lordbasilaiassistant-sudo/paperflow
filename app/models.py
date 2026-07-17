from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None


class Extraction(BaseModel):
    vendor: str | None = None
    date: str | None = None  # ISO YYYY-MM-DD after normalization
    invoice_no: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    currency: str | None = None


class ValidationIssue(BaseModel):
    field: str
    code: str
    message: str
    severity: str = "error"  # "error" | "warning"


SCALAR_FIELDS = ["vendor", "date", "invoice_no", "subtotal", "tax", "total", "currency"]
REQUIRED_FIELDS = ["vendor", "date", "total"]

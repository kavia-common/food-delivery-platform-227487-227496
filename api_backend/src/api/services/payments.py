from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4


@dataclass(frozen=True)
class PaymentIntent:
    provider: str
    provider_payment_id: str
    order_id: UUID
    amount_cents: int
    currency: str


class PaymentProvider(Protocol):
    """Interface for payment providers (mockable/swappable)."""

    # PUBLIC_INTERFACE
    def create_payment_intent(self, *, order_id: UUID, amount_cents: int, currency: str) -> PaymentIntent:
        """Create a payment intent for an order."""


class MockPaymentProvider:
    """Mock provider that generates deterministic-ish IDs and 'processing' intents."""

    # PUBLIC_INTERFACE
    def create_payment_intent(self, *, order_id: UUID, amount_cents: int, currency: str) -> PaymentIntent:
        """Create a mock payment intent."""
        return PaymentIntent(
            provider="mock",
            provider_payment_id=f"mock_pi_{uuid4().hex[:12]}",
            order_id=order_id,
            amount_cents=amount_cents,
            currency=currency,
        )


# PUBLIC_INTERFACE
def get_payment_provider() -> PaymentProvider:
    """Return the active payment provider implementation."""
    return MockPaymentProvider()

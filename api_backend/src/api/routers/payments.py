from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_db_session
from src.api.deps import AuthUser, get_current_user, require_roles
from src.api.schemas import (
    CreatePaymentIntentRequest,
    PaymentRecordOut,
    UpdatePaymentStatusRequest,
)
from src.api.services.payments import get_payment_provider
from src.api.services.tracking import TrackingMessage, tracking_hub

router = APIRouter(prefix="/payments", tags=["payments"])


async def _assert_order_access(session: AsyncSession, user: AuthUser, order_id: UUID) -> None:
    meta = (
        await session.execute(
            text(
                """
                SELECT o.customer_user_id, r.owner_user_id
                FROM orders o
                JOIN restaurants r ON r.id = o.restaurant_id
                WHERE o.id = :id
                """
            ),
            {"id": str(order_id)},
        )
    ).mappings().first()
    if not meta:
        raise HTTPException(status_code=404, detail="Order not found")
    if user.role == "admin":
        return
    if user.role == "customer" and str(meta["customer_user_id"]) == str(user.id):
        return
    if user.role == "restaurant" and str(meta["owner_user_id"]) == str(user.id):
        return
    raise HTTPException(status_code=403, detail="Not permitted")


@router.post(
    "/intent",
    response_model=PaymentRecordOut,
    summary="Create payment intent (mock)",
    description="Creates a mock payment intent and a payment_records row in 'processing'.",
)
async def create_payment_intent(
    payload: CreatePaymentIntentRequest,
    user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PaymentRecordOut:
    """Create payment intent for an order."""
    await _assert_order_access(session, user, payload.order_id)

    order = (
        await session.execute(
            text("SELECT total_cents, currency, status FROM orders WHERE id = :id"),
            {"id": str(payload.order_id)},
        )
    ).mappings().first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    provider = get_payment_provider()
    intent = provider.create_payment_intent(
        order_id=payload.order_id, amount_cents=int(order["total_cents"]), currency=order["currency"]
    )

    row = (
        await session.execute(
            text(
                """
                INSERT INTO payment_records (order_id, provider, provider_payment_id, status, amount_cents, currency)
                VALUES (:order_id, :provider, :provider_payment_id, 'processing', :amount_cents, :currency)
                RETURNING id, order_id, provider, provider_payment_id, status, amount_cents, currency, created_at
                """
            ),
            {
                "order_id": str(payload.order_id),
                "provider": intent.provider,
                "provider_payment_id": intent.provider_payment_id,
                "amount_cents": intent.amount_cents,
                "currency": intent.currency,
            },
        )
    ).mappings().first()
    await tracking_hub.publish(
        payload.order_id,
        TrackingMessage(type="payment_intent_created", payload={"provider_payment_id": intent.provider_payment_id}),
    )
    await session.commit()
    return PaymentRecordOut(**row)


@router.post(
    "/{payment_id}/status",
    response_model=PaymentRecordOut,
    summary="Update payment status",
    description="Update payment status (admin only). If succeeded, also updates order to 'paid' when currently 'pending_payment'.",
)
async def update_payment_status(
    payment_id: UUID,
    payload: UpdatePaymentStatusRequest,
    user: AuthUser = Depends(require_roles("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> PaymentRecordOut:
    """Admin updates payment status."""
    payment = (
        await session.execute(
            text(
                """
                SELECT id, order_id, status
                FROM payment_records
                WHERE id = :id
                """
            ),
            {"id": str(payment_id)},
        )
    ).mappings().first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment record not found")

    row = (
        await session.execute(
            text(
                """
                UPDATE payment_records
                SET status = :status
                WHERE id = :id
                RETURNING id, order_id, provider, provider_payment_id, status, amount_cents, currency, created_at
                """
            ),
            {"id": str(payment_id), "status": payload.status},
        )
    ).mappings().first()

    # If payment succeeded, move order to paid
    if payload.status == "succeeded":
        await session.execute(
            text(
                """
                UPDATE orders
                SET status = 'paid'
                WHERE id = :order_id AND status = 'pending_payment'
                """
            ),
            {"order_id": str(payment["order_id"])},
        )

    await session.commit()
    return PaymentRecordOut(**row)


@router.get(
    "/order/{order_id}",
    response_model=List[PaymentRecordOut],
    summary="List payment records for order",
    description="List payment records. Customer/restaurant(owner)/admin allowed.",
)
async def list_payments_for_order(
    order_id: UUID,
    user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> List[PaymentRecordOut]:
    """List payment records for an order."""
    await _assert_order_access(session, user, order_id)

    rows = (
        await session.execute(
            text(
                """
                SELECT id, order_id, provider, provider_payment_id, status, amount_cents, currency, created_at
                FROM payment_records
                WHERE order_id = :order_id
                ORDER BY created_at DESC
                """
            ),
            {"order_id": str(order_id)},
        )
    ).mappings().all()
    return [PaymentRecordOut(**r) for r in rows]

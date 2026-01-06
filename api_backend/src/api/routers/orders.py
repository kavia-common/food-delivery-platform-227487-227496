from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_db_session
from src.api.deps import AuthUser, get_current_user, require_roles
from src.api.schemas import CreateOrderRequest, OrderItemOut, OrderOut, UpdateOrderStatusRequest
from src.api.services.tracking import TrackingMessage, tracking_hub

router = APIRouter(prefix="/orders", tags=["orders"])

# DB enum order_status:
# pending_payment, paid, accepted, preparing, ready_for_pickup, picked_up, delivered, cancelled, refunded
STATUS_FLOW = {
    "pending_payment": {"paid", "cancelled"},
    "paid": {"accepted", "cancelled"},
    "accepted": {"preparing", "cancelled"},
    "preparing": {"ready_for_pickup", "cancelled"},
    "ready_for_pickup": {"picked_up", "cancelled"},
    "picked_up": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
    "refunded": set(),
}


async def _emit_tracking(
    session: AsyncSession,
    order_id: UUID,
    event_type: str,
    message: Optional[str] = None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO tracking_events (order_id, event_type, event_message)
            VALUES (:order_id, :event_type, :event_message)
            """
        ),
        {"order_id": str(order_id), "event_type": event_type, "event_message": message},
    )
    # Publish to websocket subscribers as well
    await tracking_hub.publish(
        order_id,
        TrackingMessage(type="tracking_event", payload={"event_type": event_type, "event_message": message}),
    )


async def _get_order_with_items(session: AsyncSession, order_id: UUID) -> OrderOut:
    order = (
        await session.execute(
            text(
                """
                SELECT id, customer_user_id, restaurant_id, status, currency, subtotal_cents,
                       delivery_fee_cents, tax_cents, total_cents,
                       delivery_address_line1, delivery_address_line2, delivery_city, delivery_state, delivery_postal_code,
                       notes, placed_at, created_at
                FROM orders
                WHERE id = :id
                """
            ),
            {"id": str(order_id)},
        )
    ).mappings().first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    items = (
        await session.execute(
            text(
                """
                SELECT id, menu_item_id, name_snapshot, unit_price_cents_snapshot, quantity, line_total_cents
                FROM order_items
                WHERE order_id = :order_id
                ORDER BY created_at ASC
                """
            ),
            {"order_id": str(order_id)},
        )
    ).mappings().all()
    return OrderOut(**order, items=[OrderItemOut(**i) for i in items])


@router.post(
    "",
    response_model=OrderOut,
    summary="Create order from cart payload",
    description="Customer creates an order with line items and delivery address. Starts in 'pending_payment'.",
)
async def create_order(
    payload: CreateOrderRequest,
    user: AuthUser = Depends(require_roles("customer", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> OrderOut:
    """Create an order and order_items based on current menu item prices."""
    # Load menu item snapshots and compute totals
    menu_item_ids = [str(i.menu_item_id) for i in payload.items]
    if len(menu_item_ids) != len(set(menu_item_ids)):
        raise HTTPException(status_code=400, detail="Duplicate menu_item_id in cart")

    price_rows = (
        await session.execute(
            text(
                """
                SELECT mi.id, mi.name, mi.price_cents, mi.currency, mi.is_available, m.restaurant_id
                FROM menu_items mi
                JOIN menus m ON m.id = mi.menu_id
                WHERE mi.id = ANY(:ids)
                """
            ),
            {"ids": menu_item_ids},
        )
    ).mappings().all()
    if len(price_rows) != len(menu_item_ids):
        raise HTTPException(status_code=400, detail="One or more items not found")

    # Validate restaurant match and availability
    for r in price_rows:
        if str(r["restaurant_id"]) != str(payload.restaurant_id):
            raise HTTPException(status_code=400, detail="All items must belong to the same restaurant")
        if not r["is_available"]:
            raise HTTPException(status_code=400, detail=f"Item not available: {r['name']}")

    price_map = {str(r["id"]): r for r in price_rows}
    currency = price_rows[0]["currency"]

    subtotal = 0
    item_snapshots = []
    for cart_item in payload.items:
        src = price_map[str(cart_item.menu_item_id)]
        line_total = int(src["price_cents"]) * int(cart_item.quantity)
        subtotal += line_total
        item_snapshots.append(
            {
                "menu_item_id": str(cart_item.menu_item_id),
                "name_snapshot": src["name"],
                "unit_price_cents_snapshot": int(src["price_cents"]),
                "quantity": int(cart_item.quantity),
                "line_total_cents": line_total,
            }
        )

    # Simple fees/tax placeholders
    delivery_fee = 399 if subtotal > 0 else 0
    tax = int(round(subtotal * 0.10))
    total = subtotal + delivery_fee + tax

    now = datetime.now(timezone.utc)
    order = (
        await session.execute(
            text(
                """
                INSERT INTO orders (
                    customer_user_id, restaurant_id, status, currency,
                    subtotal_cents, delivery_fee_cents, tax_cents, total_cents,
                    delivery_address_line1, delivery_address_line2, delivery_city, delivery_state, delivery_postal_code,
                    notes, placed_at
                )
                VALUES (
                    :customer_user_id, :restaurant_id, 'pending_payment', :currency,
                    :subtotal_cents, :delivery_fee_cents, :tax_cents, :total_cents,
                    :delivery_address_line1, :delivery_address_line2, :delivery_city, :delivery_state, :delivery_postal_code,
                    :notes, :placed_at
                )
                RETURNING id
                """
            ),
            {
                "customer_user_id": str(user.id),
                "restaurant_id": str(payload.restaurant_id),
                "currency": currency,
                "subtotal_cents": subtotal,
                "delivery_fee_cents": delivery_fee,
                "tax_cents": tax,
                "total_cents": total,
                "delivery_address_line1": payload.delivery_address_line1,
                "delivery_address_line2": payload.delivery_address_line2,
                "delivery_city": payload.delivery_city,
                "delivery_state": payload.delivery_state,
                "delivery_postal_code": payload.delivery_postal_code,
                "notes": payload.notes,
                "placed_at": now,
            },
        )
    ).mappings().first()
    order_id = UUID(str(order["id"]))

    for snap in item_snapshots:
        await session.execute(
            text(
                """
                INSERT INTO order_items (
                    order_id, menu_item_id, name_snapshot, unit_price_cents_snapshot, quantity, line_total_cents
                )
                VALUES (
                    :order_id, :menu_item_id, :name_snapshot, :unit_price_cents_snapshot, :quantity, :line_total_cents
                )
                """
            ),
            {"order_id": str(order_id), **snap},
        )

    await _emit_tracking(session, order_id, "order_created", "Order created (pending payment).")
    await session.commit()

    return await _get_order_with_items(session, order_id)


@router.get(
    "/my/current",
    response_model=List[OrderOut],
    summary="Customer current orders",
    description="Customer views active orders (not delivered/cancelled/refunded).",
)
async def my_current_orders(
    user: AuthUser = Depends(require_roles("customer", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> List[OrderOut]:
    """List current orders for customer."""
    rows = (
        await session.execute(
            text(
                """
                SELECT id
                FROM orders
                WHERE customer_user_id = :uid
                  AND status NOT IN ('delivered', 'cancelled', 'refunded')
                ORDER BY created_at DESC
                """
            ),
            {"uid": str(user.id)},
        )
    ).mappings().all()
    return [await _get_order_with_items(session, UUID(str(r["id"]))) for r in rows]


@router.get(
    "/my/history",
    response_model=List[OrderOut],
    summary="Customer order history",
    description="Customer views completed/cancelled orders.",
)
async def my_order_history(
    user: AuthUser = Depends(require_roles("customer", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> List[OrderOut]:
    """List past orders for customer."""
    rows = (
        await session.execute(
            text(
                """
                SELECT id
                FROM orders
                WHERE customer_user_id = :uid
                  AND status IN ('delivered', 'cancelled', 'refunded')
                ORDER BY created_at DESC
                """
            ),
            {"uid": str(user.id)},
        )
    ).mappings().all()
    return [await _get_order_with_items(session, UUID(str(r["id"]))) for r in rows]


@router.get(
    "/{order_id}",
    response_model=OrderOut,
    summary="Get order",
    description="Get an order by id (customer who owns it, restaurant owner, courier assigned, or admin).",
)
async def get_order(
    order_id: UUID,
    user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> OrderOut:
    """Get order by id with access control."""
    meta = (
        await session.execute(
            text(
                """
                SELECT o.customer_user_id, r.owner_user_id,
                       da.courier_user_id
                FROM orders o
                JOIN restaurants r ON r.id = o.restaurant_id
                LEFT JOIN delivery_assignments da ON da.order_id = o.id
                WHERE o.id = :id
                """
            ),
            {"id": str(order_id)},
        )
    ).mappings().first()
    if not meta:
        raise HTTPException(status_code=404, detail="Order not found")

    allowed = (
        user.role == "admin"
        or str(meta["customer_user_id"]) == str(user.id)
        or str(meta["owner_user_id"]) == str(user.id)
        or (meta["courier_user_id"] is not None and str(meta["courier_user_id"]) == str(user.id))
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Not permitted")
    return await _get_order_with_items(session, order_id)


@router.post(
    "/{order_id}/status",
    response_model=OrderOut,
    summary="Update order status",
    description=(
        "Update order status with role enforcement:\n"
        "- customer/admin: can cancel when not delivered\n"
        "- restaurant/admin: can move paid->accepted->preparing->ready_for_pickup\n"
        "- delivery/admin: can move ready_for_pickup->picked_up->delivered\n"
    ),
)
async def update_order_status(
    order_id: UUID,
    payload: UpdateOrderStatusRequest,
    user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> OrderOut:
    """Update order status with allowed transitions and role checks."""
    current = (
        await session.execute(
            text(
                """
                SELECT o.status, o.customer_user_id, o.restaurant_id, r.owner_user_id
                FROM orders o
                JOIN restaurants r ON r.id = o.restaurant_id
                WHERE o.id = :id
                """
            ),
            {"id": str(order_id)},
        )
    ).mappings().first()
    if not current:
        raise HTTPException(status_code=404, detail="Order not found")

    old = current["status"]
    new = payload.status
    if new not in STATUS_FLOW.get(old, set()):
        raise HTTPException(status_code=400, detail=f"Invalid status transition {old} -> {new}")

    # Role enforcement
    if user.role == "customer":
        if str(current["customer_user_id"]) != str(user.id):
            raise HTTPException(status_code=403, detail="Not permitted")
        if new != "cancelled":
            raise HTTPException(status_code=403, detail="Customers can only cancel")
    elif user.role == "restaurant":
        if str(current["owner_user_id"]) != str(user.id):
            raise HTTPException(status_code=403, detail="Not permitted")
        if new not in {"accepted", "preparing", "ready_for_pickup", "cancelled"}:
            raise HTTPException(status_code=403, detail="Restaurant cannot set that status")
    elif user.role == "delivery":
        # Must be assigned
        assignment = (
            await session.execute(
                text("SELECT courier_user_id FROM delivery_assignments WHERE order_id = :oid"),
                {"oid": str(order_id)},
            )
        ).mappings().first()
        if not assignment or assignment["courier_user_id"] is None or str(assignment["courier_user_id"]) != str(user.id):
            raise HTTPException(status_code=403, detail="Courier not assigned to this order")
        if new not in {"picked_up", "delivered"}:
            raise HTTPException(status_code=403, detail="Courier cannot set that status")
    else:
        # admin can do any valid transition
        pass

    await session.execute(
        text("UPDATE orders SET status = :status WHERE id = :id"),
        {"status": new, "id": str(order_id)},
    )

    # Update delivery_assignments status when appropriate
    if new == "picked_up":
        await session.execute(
            text(
                """
                UPDATE delivery_assignments
                SET status = 'picked_up', picked_up_at = NOW()
                WHERE order_id = :oid
                """
            ),
            {"oid": str(order_id)},
        )
    if new == "delivered":
        await session.execute(
            text(
                """
                UPDATE delivery_assignments
                SET status = 'delivered', delivered_at = NOW()
                WHERE order_id = :oid
                """
            ),
            {"oid": str(order_id)},
        )

    await _emit_tracking(session, order_id, f"status_{new}", f"Order status updated to {new}.")
    await session.commit()
    return await _get_order_with_items(session, order_id)


@router.post(
    "/{order_id}/assign",
    summary="Assign courier to order",
    description="Assign a courier (admin only). Creates/updates delivery_assignment.",
)
async def assign_courier(
    order_id: UUID,
    courier_user_id: UUID,
    user: AuthUser = Depends(require_roles("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Admin assigns a courier to an order."""
    # ensure order exists
    exists = (await session.execute(text("SELECT 1 FROM orders WHERE id = :id"), {"id": str(order_id)})).first()
    if not exists:
        raise HTTPException(status_code=404, detail="Order not found")

    await session.execute(
        text(
            """
            INSERT INTO delivery_assignments (order_id, courier_user_id, status, assigned_at)
            VALUES (:order_id, :courier_user_id, 'assigned', NOW())
            ON CONFLICT (order_id) DO UPDATE
              SET courier_user_id = EXCLUDED.courier_user_id,
                  status = 'assigned',
                  assigned_at = NOW()
            """
        ),
        {"order_id": str(order_id), "courier_user_id": str(courier_user_id)},
    )
    await _emit_tracking(session, order_id, "courier_assigned", "Courier assigned.")
    await session.commit()
    return {"message": "Assigned"}

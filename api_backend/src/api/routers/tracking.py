from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_db_session
from src.api.deps import AuthUser, get_current_user
from src.api.schemas import TrackingEventOut, TrackingPublishRequest
from src.api.services.tracking import TrackingMessage, tracking_hub

router = APIRouter(prefix="/tracking", tags=["tracking"])


async def _assert_order_access(session: AsyncSession, user: AuthUser, order_id: UUID) -> None:
    meta = (
        await session.execute(
            text(
                """
                SELECT o.customer_user_id, r.owner_user_id, da.courier_user_id
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
    if user.role == "admin":
        return
    if user.role == "customer" and str(meta["customer_user_id"]) == str(user.id):
        return
    if user.role == "restaurant" and str(meta["owner_user_id"]) == str(user.id):
        return
    if user.role == "delivery" and meta["courier_user_id"] is not None and str(meta["courier_user_id"]) == str(user.id):
        return
    raise HTTPException(status_code=403, detail="Not permitted")


@router.get(
    "/orders/{order_id}/events",
    response_model=List[TrackingEventOut],
    summary="Poll tracking events for an order",
    description="Polling fallback to retrieve tracking timeline for an order.",
)
async def list_tracking_events(
    order_id: UUID,
    user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> List[TrackingEventOut]:
    """List tracking events for an order (polling fallback)."""
    await _assert_order_access(session, user, order_id)
    rows = (
        await session.execute(
            text(
                """
                SELECT id, order_id, event_type, event_message, latitude, longitude, created_at
                FROM tracking_events
                WHERE order_id = :order_id
                ORDER BY created_at ASC
                """
            ),
            {"order_id": str(order_id)},
        )
    ).mappings().all()
    return [TrackingEventOut(**r) for r in rows]


@router.post(
    "/orders/{order_id}/events",
    summary="Publish tracking event",
    description="Publish a tracking event. Restaurant/courier/admin can publish events.",
)
async def publish_tracking_event(
    order_id: UUID,
    payload: TrackingPublishRequest,
    user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Publish a new tracking event to DB and websocket subscribers."""
    if user.role not in ("restaurant", "delivery", "admin"):
        raise HTTPException(status_code=403, detail="Not permitted")

    # Enforce access to the order for restaurant/courier
    await _assert_order_access(session, user, order_id)

    await session.execute(
        text(
            """
            INSERT INTO tracking_events (order_id, event_type, event_message, latitude, longitude)
            VALUES (:order_id, :event_type, :event_message, :latitude, :longitude)
            """
        ),
        {"order_id": str(order_id), **payload.model_dump()},
    )
    await tracking_hub.publish(
        order_id, TrackingMessage(type="tracking_event", payload=payload.model_dump())
    )
    await session.commit()
    return {"message": "Published"}


@router.websocket("/ws/orders/{order_id}")
async def order_tracking_ws(websocket: WebSocket, order_id: UUID) -> None:
    """Real-time tracking WebSocket.

    Client usage:
      - Connect to: ws(s)://<host>/tracking/ws/orders/<order_id>
      - (Optional) send Authorization header is not supported by browsers consistently.
        If you need auth here, pass token via query param '?token=...'.
        For now, this websocket is open; polling endpoints enforce auth.

    Server sends JSON messages:
      {"type": "...", "payload": {...}}
    """
    await websocket.accept()
    await tracking_hub.subscribe(order_id, websocket)
    try:
        # Keep alive; we don't require client messages but can receive pings.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await tracking_hub.unsubscribe(order_id, websocket)

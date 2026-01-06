from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.settings import get_settings
from src.api.db import get_db_session
from src.api.deps import require_roles

router = APIRouter(prefix="/dev", tags=["dev"])


@router.post(
    "/reset_seed",
    summary="Reset DB to minimal seed state (DEV ONLY)",
    description="Deletes data and re-inserts minimal seed records. Guarded by BACKEND_ENABLE_DEV_ADMIN=true and admin role.",
)
async def reset_seed(
    _admin=Depends(require_roles("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """DEV helper to reset key tables to the known seed data."""
    settings = get_settings()
    if not settings.enable_dev_admin:
        raise HTTPException(status_code=403, detail="Dev admin routes disabled")

    # Wipe in safe order
    await session.execute(text("DELETE FROM tracking_events"))
    await session.execute(text("DELETE FROM payment_records"))
    await session.execute(text("DELETE FROM delivery_assignments"))
    await session.execute(text("DELETE FROM order_items"))
    await session.execute(text("DELETE FROM orders"))
    await session.execute(text("DELETE FROM menu_items"))
    await session.execute(text("DELETE FROM menus"))
    await session.execute(text("DELETE FROM restaurants"))
    await session.execute(text("DELETE FROM users"))

    # Reinsert seed (matching migrations/002_seed_minimal_data.sql)
    await session.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash, full_name, role, phone)
            VALUES
              ('11111111-1111-1111-1111-111111111111', 'customer1@example.com', 'demo_password_hash', 'Casey Customer', 'customer', '+15550000001'),
              ('22222222-2222-2222-2222-222222222222', 'owner1@example.com',    'demo_password_hash', 'Riley RestaurantOwner', 'restaurant', '+15550000002'),
              ('33333333-3333-3333-3333-333333333333', 'courier1@example.com',  'demo_password_hash', 'Drew Delivery', 'delivery', '+15550000003'),
              ('99999999-9999-9999-9999-999999999999', 'admin@example.com',     'demo_password_hash', 'Alex Admin', 'admin', '+15550000009')
            """
        )
    )

    await session.execute(
        text(
            """
            INSERT INTO restaurants (
              id, owner_user_id, name, description,
              address_line1, city, state, postal_code,
              latitude, longitude, is_open
            )
            VALUES
              (
                'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                '22222222-2222-2222-2222-222222222222',
                'Pasta Palace',
                'Fresh pasta, salads, and Italian comfort food.',
                '123 Noodle St', 'San Francisco', 'CA', '94105',
                37.7890, -122.3942, TRUE
              ),
              (
                'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                '22222222-2222-2222-2222-222222222222',
                'Sushi Station',
                'Nigiri, rolls, and bento boxes made daily.',
                '456 Wasabi Ave', 'San Francisco', 'CA', '94107',
                37.7765, -122.3947, TRUE
              )
            """
        )
    )

    await session.execute(
        text(
            """
            INSERT INTO menus (id, restaurant_id, name, is_active)
            VALUES
              ('aaaaaaaa-0000-0000-0000-000000000001', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Main Menu', TRUE),
              ('bbbbbbbb-0000-0000-0000-000000000001', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'Main Menu', TRUE)
            """
        )
    )

    await session.execute(
        text(
            """
            INSERT INTO menu_items (id, menu_id, name, description, price_cents, currency, is_available)
            VALUES
              ('aaaa0000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-000000000001', 'Spaghetti Carbonara', 'Creamy sauce, pancetta, parmesan.', 1599, 'USD', TRUE),
              ('aaaa0000-0000-0000-0000-000000000002', 'aaaaaaaa-0000-0000-0000-000000000001', 'Margherita Flatbread', 'Tomato, mozzarella, basil.', 1299, 'USD', TRUE),
              ('aaaa0000-0000-0000-0000-000000000003', 'aaaaaaaa-0000-0000-0000-000000000001', 'House Salad', 'Mixed greens, lemon vinaigrette.', 799, 'USD', TRUE),
              ('bbbb0000-0000-0000-0000-000000000001', 'bbbbbbbb-0000-0000-0000-000000000001', 'Salmon Nigiri (6pc)', 'Fresh salmon over sushi rice.', 1399, 'USD', TRUE),
              ('bbbb0000-0000-0000-0000-000000000002', 'bbbbbbbb-0000-0000-0000-000000000001', 'California Roll', 'Crab, avocado, cucumber.', 999, 'USD', TRUE),
              ('bbbb0000-0000-0000-0000-000000000003', 'bbbbbbbb-0000-0000-0000-000000000001', 'Chicken Teriyaki Bento', 'Rice, salad, teriyaki chicken.', 1699, 'USD', TRUE)
            """
        )
    )

    await session.commit()
    return {"message": "Reset complete"}

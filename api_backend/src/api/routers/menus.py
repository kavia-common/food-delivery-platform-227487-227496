from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_db_session
from src.api.deps import AuthUser, require_roles
from src.api.schemas import (
    MenuCreate,
    MenuItemCreate,
    MenuItemOut,
    MenuItemUpdate,
    MenuOut,
    MenuWithItemsOut,
)

router = APIRouter(prefix="/menus", tags=["menus"])


async def _assert_owner_or_admin_for_restaurant(session: AsyncSession, user: AuthUser, restaurant_id: UUID) -> None:
    row = (
        await session.execute(
            text("SELECT owner_user_id FROM restaurants WHERE id = :id"),
            {"id": str(restaurant_id)},
        )
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    if user.role != "admin" and str(row["owner_user_id"]) != str(user.id):
        raise HTTPException(status_code=403, detail="Not permitted")


@router.get(
    "/restaurant/{restaurant_id}",
    response_model=List[MenuOut],
    summary="List menus for a restaurant",
    description="Public endpoint to list menus for a restaurant.",
)
async def list_menus_for_restaurant(restaurant_id: UUID, session: AsyncSession = Depends(get_db_session)) -> List[MenuOut]:
    """List menus for a restaurant (public)."""
    rows = (
        await session.execute(
            text(
                """
                SELECT id, restaurant_id, name, is_active, created_at
                FROM menus
                WHERE restaurant_id = :restaurant_id
                ORDER BY created_at ASC
                """
            ),
            {"restaurant_id": str(restaurant_id)},
        )
    ).mappings().all()
    return [MenuOut(**r) for r in rows]


@router.get(
    "/{menu_id}/items",
    response_model=MenuWithItemsOut,
    summary="Get menu items",
    description="Public endpoint to get menu metadata and all items.",
)
async def get_menu_with_items(menu_id: UUID, session: AsyncSession = Depends(get_db_session)) -> MenuWithItemsOut:
    """Get a menu with its items (public)."""
    menu = (
        await session.execute(
            text("SELECT id, restaurant_id, name, is_active, created_at FROM menus WHERE id = :id"),
            {"id": str(menu_id)},
        )
    ).mappings().first()
    if not menu:
        raise HTTPException(status_code=404, detail="Menu not found")

    items = (
        await session.execute(
            text(
                """
                SELECT id, menu_id, name, description, price_cents, currency, is_available, image_url, created_at
                FROM menu_items
                WHERE menu_id = :menu_id
                ORDER BY created_at ASC
                """
            ),
            {"menu_id": str(menu_id)},
        )
    ).mappings().all()
    return MenuWithItemsOut(menu=MenuOut(**menu), items=[MenuItemOut(**i) for i in items])


@router.post(
    "",
    response_model=MenuOut,
    summary="Create menu",
    description="Create a menu for a restaurant. Allowed roles: restaurant(owner), admin.",
)
async def create_menu(
    payload: MenuCreate,
    user: AuthUser = Depends(require_roles("restaurant", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> MenuOut:
    """Create menu (owner/admin)."""
    await _assert_owner_or_admin_for_restaurant(session, user, payload.restaurant_id)
    try:
        row = (
            await session.execute(
                text(
                    """
                    INSERT INTO menus (restaurant_id, name, is_active)
                    VALUES (:restaurant_id, :name, :is_active)
                    RETURNING id, restaurant_id, name, is_active, created_at
                    """
                ),
                {"restaurant_id": str(payload.restaurant_id), "name": payload.name, "is_active": payload.is_active},
            )
        ).mappings().first()
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Menu name already exists for this restaurant")
    return MenuOut(**row)


@router.delete(
    "/{menu_id}",
    summary="Delete menu",
    description="Delete a menu. Owner/admin only.",
)
async def delete_menu(
    menu_id: UUID,
    user: AuthUser = Depends(require_roles("restaurant", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Delete menu (owner/admin)."""
    menu = (
        await session.execute(
            text("SELECT id, restaurant_id FROM menus WHERE id = :id"),
            {"id": str(menu_id)},
        )
    ).mappings().first()
    if not menu:
        raise HTTPException(status_code=404, detail="Menu not found")
    await _assert_owner_or_admin_for_restaurant(session, user, UUID(str(menu["restaurant_id"])))
    await session.execute(text("DELETE FROM menus WHERE id = :id"), {"id": str(menu_id)})
    await session.commit()
    return {"message": "Deleted"}


@router.post(
    "/items",
    response_model=MenuItemOut,
    summary="Create menu item",
    description="Create a menu item. Owner/admin only.",
)
async def create_menu_item(
    payload: MenuItemCreate,
    user: AuthUser = Depends(require_roles("restaurant", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> MenuItemOut:
    """Create menu item (owner/admin)."""
    menu = (
        await session.execute(
            text("SELECT id, restaurant_id FROM menus WHERE id = :id"),
            {"id": str(payload.menu_id)},
        )
    ).mappings().first()
    if not menu:
        raise HTTPException(status_code=404, detail="Menu not found")

    await _assert_owner_or_admin_for_restaurant(session, user, UUID(str(menu["restaurant_id"])))

    row = (
        await session.execute(
            text(
                """
                INSERT INTO menu_items (
                    menu_id, name, description, price_cents, currency, is_available, image_url
                )
                VALUES (
                    :menu_id, :name, :description, :price_cents, :currency, :is_available, :image_url
                )
                RETURNING id, menu_id, name, description, price_cents, currency, is_available, image_url, created_at
                """
            ),
            {"menu_id": str(payload.menu_id), **payload.model_dump(exclude={"menu_id"})},
        )
    ).mappings().first()
    await session.commit()
    return MenuItemOut(**row)


@router.patch(
    "/items/{item_id}",
    response_model=MenuItemOut,
    summary="Update menu item",
    description="Update menu item. Owner/admin only.",
)
async def update_menu_item(
    item_id: UUID,
    payload: MenuItemUpdate,
    user: AuthUser = Depends(require_roles("restaurant", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> MenuItemOut:
    """Update menu item (owner/admin)."""
    item = (
        await session.execute(
            text(
                """
                SELECT mi.id, m.restaurant_id
                FROM menu_items mi
                JOIN menus m ON m.id = mi.menu_id
                WHERE mi.id = :id
                """
            ),
            {"id": str(item_id)},
        )
    ).mappings().first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    await _assert_owner_or_admin_for_restaurant(session, user, UUID(str(item["restaurant_id"])))

    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_expr = ", ".join([f"{k} = :{k}" for k in fields.keys()])
    row = (
        await session.execute(
            text(
                f"""
                UPDATE menu_items
                SET {set_expr}
                WHERE id = :id
                RETURNING id, menu_id, name, description, price_cents, currency, is_available, image_url, created_at
                """
            ),
            {"id": str(item_id), **fields},
        )
    ).mappings().first()
    await session.commit()
    return MenuItemOut(**row)


@router.delete(
    "/items/{item_id}",
    summary="Delete menu item",
    description="Delete menu item. Owner/admin only.",
)
async def delete_menu_item(
    item_id: UUID,
    user: AuthUser = Depends(require_roles("restaurant", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Delete menu item (owner/admin)."""
    item = (
        await session.execute(
            text(
                """
                SELECT mi.id, m.restaurant_id
                FROM menu_items mi
                JOIN menus m ON m.id = mi.menu_id
                WHERE mi.id = :id
                """
            ),
            {"id": str(item_id)},
        )
    ).mappings().first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    await _assert_owner_or_admin_for_restaurant(session, user, UUID(str(item["restaurant_id"])))
    await session.execute(text("DELETE FROM menu_items WHERE id = :id"), {"id": str(item_id)})
    await session.commit()
    return {"message": "Deleted"}

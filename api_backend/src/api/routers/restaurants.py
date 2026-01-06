from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_db_session
from src.api.deps import AuthUser, get_current_user, require_roles
from src.api.schemas import RestaurantCreate, RestaurantOut, RestaurantUpdate

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


@router.get(
    "",
    response_model=List[RestaurantOut],
    summary="List restaurants",
    description="Public endpoint to list restaurants with optional city filter.",
)
async def list_restaurants(
    city: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
) -> List[RestaurantOut]:
    """List restaurants (public)."""
    if city:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, owner_user_id, name, description, address_line1, address_line2,
                           city, state, postal_code, latitude, longitude, is_open, created_at
                    FROM restaurants
                    WHERE city ILIKE :city
                    ORDER BY created_at DESC
                    """
                ),
                {"city": city},
            )
        ).mappings().all()
    else:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, owner_user_id, name, description, address_line1, address_line2,
                           city, state, postal_code, latitude, longitude, is_open, created_at
                    FROM restaurants
                    ORDER BY created_at DESC
                    """
                )
            )
        ).mappings().all()
    return [RestaurantOut(**r) for r in rows]


@router.get(
    "/{restaurant_id}",
    response_model=RestaurantOut,
    summary="Get restaurant",
    description="Public endpoint to fetch a restaurant by id.",
)
async def get_restaurant(restaurant_id: UUID, session: AsyncSession = Depends(get_db_session)) -> RestaurantOut:
    """Get restaurant details (public)."""
    row = (
        await session.execute(
            text(
                """
                SELECT id, owner_user_id, name, description, address_line1, address_line2,
                       city, state, postal_code, latitude, longitude, is_open, created_at
                FROM restaurants
                WHERE id = :id
                """
            ),
            {"id": str(restaurant_id)},
        )
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return RestaurantOut(**row)


@router.post(
    "",
    response_model=RestaurantOut,
    summary="Create restaurant",
    description="Create a restaurant. Allowed roles: restaurant(owner), admin.",
)
async def create_restaurant(
    payload: RestaurantCreate,
    user: AuthUser = Depends(require_roles("restaurant", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> RestaurantOut:
    """Create a restaurant owned by the current user (or admin can also create)."""
    owner_id = str(user.id)
    row = (
        await session.execute(
            text(
                """
                INSERT INTO restaurants (
                    owner_user_id, name, description,
                    address_line1, address_line2, city, state, postal_code,
                    latitude, longitude, is_open
                )
                VALUES (
                    :owner_user_id, :name, :description,
                    :address_line1, :address_line2, :city, :state, :postal_code,
                    :latitude, :longitude, :is_open
                )
                RETURNING id, owner_user_id, name, description, address_line1, address_line2,
                          city, state, postal_code, latitude, longitude, is_open, created_at
                """
            ),
            {"owner_user_id": owner_id, **payload.model_dump()},
        )
    ).mappings().first()
    await session.commit()
    return RestaurantOut(**row)


@router.patch(
    "/{restaurant_id}",
    response_model=RestaurantOut,
    summary="Update restaurant",
    description="Update a restaurant. Only the owner or admin may update.",
)
async def update_restaurant(
    restaurant_id: UUID,
    payload: RestaurantUpdate,
    user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RestaurantOut:
    """Update restaurant (owner/admin)."""
    current = (
        await session.execute(
            text("SELECT owner_user_id FROM restaurants WHERE id = :id"),
            {"id": str(restaurant_id)},
        )
    ).mappings().first()
    if not current:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    if user.role != "admin" and str(current["owner_user_id"]) != str(user.id):
        raise HTTPException(status_code=403, detail="Not permitted")

    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_expr = ", ".join([f"{k} = :{k}" for k in fields.keys()])
    row = (
        await session.execute(
            text(
                f"""
                UPDATE restaurants
                SET {set_expr}
                WHERE id = :id
                RETURNING id, owner_user_id, name, description, address_line1, address_line2,
                          city, state, postal_code, latitude, longitude, is_open, created_at
                """
            ),
            {"id": str(restaurant_id), **fields},
        )
    ).mappings().first()
    await session.commit()
    return RestaurantOut(**row)


@router.delete(
    "/{restaurant_id}",
    summary="Delete restaurant",
    description="Delete a restaurant. Only owner or admin may delete.",
)
async def delete_restaurant(
    restaurant_id: UUID,
    user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Delete restaurant (owner/admin)."""
    current = (
        await session.execute(
            text("SELECT owner_user_id FROM restaurants WHERE id = :id"),
            {"id": str(restaurant_id)},
        )
    ).mappings().first()
    if not current:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    if user.role != "admin" and str(current["owner_user_id"]) != str(user.id):
        raise HTTPException(status_code=403, detail="Not permitted")

    await session.execute(text("DELETE FROM restaurants WHERE id = :id"), {"id": str(restaurant_id)})
    await session.commit()
    return {"message": "Deleted"}

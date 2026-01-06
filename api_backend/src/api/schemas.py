from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ApiMessage(BaseModel):
    message: str = Field(..., description="Human-readable status message.")


# ---- Auth ----
class RegisterRequest(BaseModel):
    email: str = Field(..., description="User email (unique).")
    password: str = Field(..., min_length=6, description="User password (min 6 chars).")
    full_name: str = Field(..., description="Full display name.")
    role: str = Field("customer", description="Role: customer|restaurant|delivery|admin.")
    phone: Optional[str] = Field(None, description="Optional phone number.")


class LoginRequest(BaseModel):
    email: str = Field(..., description="User email.")
    password: str = Field(..., description="User password.")


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="JWT access token.")
    token_type: str = Field("bearer", description="Token type.")


class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    phone: Optional[str] = None
    is_active: bool
    created_at: datetime


# ---- Restaurants / Menus ----
class RestaurantCreate(BaseModel):
    name: str
    description: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_open: bool = True


class RestaurantUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_open: Optional[bool] = None


class RestaurantOut(BaseModel):
    id: UUID
    owner_user_id: UUID
    name: str
    description: Optional[str]
    address_line1: Optional[str]
    address_line2: Optional[str]
    city: Optional[str]
    state: Optional[str]
    postal_code: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    is_open: bool
    created_at: datetime


class MenuCreate(BaseModel):
    restaurant_id: UUID
    name: str
    is_active: bool = True


class MenuOut(BaseModel):
    id: UUID
    restaurant_id: UUID
    name: str
    is_active: bool
    created_at: datetime


class MenuItemCreate(BaseModel):
    menu_id: UUID
    name: str
    description: Optional[str] = None
    price_cents: int = Field(..., ge=0)
    currency: str = "USD"
    is_available: bool = True
    image_url: Optional[str] = None


class MenuItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_cents: Optional[int] = Field(None, ge=0)
    currency: Optional[str] = None
    is_available: Optional[bool] = None
    image_url: Optional[str] = None


class MenuItemOut(BaseModel):
    id: UUID
    menu_id: UUID
    name: str
    description: Optional[str]
    price_cents: int
    currency: str
    is_available: bool
    image_url: Optional[str]
    created_at: datetime


class MenuWithItemsOut(BaseModel):
    menu: MenuOut
    items: List[MenuItemOut]


# ---- Orders ----
class CartItemIn(BaseModel):
    menu_item_id: UUID
    quantity: int = Field(..., gt=0)


class CreateOrderRequest(BaseModel):
    restaurant_id: UUID
    items: List[CartItemIn] = Field(..., min_length=1)
    delivery_address_line1: str
    delivery_address_line2: Optional[str] = None
    delivery_city: str
    delivery_state: Optional[str] = None
    delivery_postal_code: Optional[str] = None
    notes: Optional[str] = None


class OrderItemOut(BaseModel):
    id: UUID
    menu_item_id: UUID
    name_snapshot: str
    unit_price_cents_snapshot: int
    quantity: int
    line_total_cents: int


class OrderOut(BaseModel):
    id: UUID
    customer_user_id: UUID
    restaurant_id: UUID
    status: str
    currency: str
    subtotal_cents: int
    delivery_fee_cents: int
    tax_cents: int
    total_cents: int
    delivery_address_line1: str
    delivery_address_line2: Optional[str]
    delivery_city: str
    delivery_state: Optional[str]
    delivery_postal_code: Optional[str]
    notes: Optional[str]
    placed_at: Optional[datetime]
    created_at: datetime
    items: List[OrderItemOut] = []


class UpdateOrderStatusRequest(BaseModel):
    status: str = Field(..., description="New order status.")


# ---- Payments ----
class CreatePaymentIntentRequest(BaseModel):
    order_id: UUID


class PaymentRecordOut(BaseModel):
    id: UUID
    order_id: UUID
    provider: str
    provider_payment_id: Optional[str]
    status: str
    amount_cents: int
    currency: str
    created_at: datetime


class UpdatePaymentStatusRequest(BaseModel):
    status: str = Field(..., description="Payment status: requires_payment|processing|succeeded|failed|refunded")


# ---- Tracking ----
class TrackingEventOut(BaseModel):
    id: UUID
    order_id: UUID
    event_type: str
    event_message: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    created_at: datetime


class TrackingPublishRequest(BaseModel):
    event_type: str
    event_message: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

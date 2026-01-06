from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.core.settings import get_settings
from src.api.routers import auth, dev, menus, orders, payments, restaurants, tracking

openapi_tags = [
    {"name": "auth", "description": "Registration, login, and current-user profile."},
    {"name": "restaurants", "description": "Restaurant listing and owner/admin CRUD."},
    {"name": "menus", "description": "Menu and menu item retrieval + owner/admin CRUD."},
    {"name": "orders", "description": "Order placement, listing, and status transitions."},
    {"name": "payments", "description": "Mock payment intent + payment record management."},
    {"name": "tracking", "description": "Tracking events and real-time order tracking websocket."},
    {"name": "dev", "description": "Development-only helpers (guarded by env + admin role)."},
]


app = FastAPI(
    title="Food Delivery Platform API",
    description=(
        "Backend API for the food delivery platform.\n\n"
        "WebSocket real-time tracking:\n"
        "- Connect to: `/tracking/ws/orders/{order_id}`\n"
        "- Server pushes JSON messages: `{\"type\": \"...\", \"payload\": {...}}`\n"
        "- Polling fallback: `GET /tracking/orders/{order_id}/events`\n"
    ),
    version="0.1.0",
    openapi_tags=openapi_tags,
)

settings = get_settings()

# CORS: allow the frontend origin(s)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(restaurants.router)
app.include_router(menus.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(tracking.router)
app.include_router(dev.router)


@app.get("/", tags=["dev"], summary="Health check", description="Simple health check endpoint.")
def health_check():
    """Backend health check."""
    return {"message": "Healthy"}


@app.get("/health", tags=["dev"], summary="Health check (alias)", description="Alias for the root health endpoint.")
def health_check_alias():
    """Backend health check alias for infra/preview smoke tests."""
    return {"status": "ok"}


@app.get("/docs/ws", tags=["tracking"], summary="WebSocket usage help", description="How to use order tracking websocket.")
def websocket_usage_help():
    """Describe WebSocket endpoints and usage."""
    return {
        "websocket": {
            "url": "/tracking/ws/orders/{order_id}",
            "messages": [{"type": "tracking_event", "payload": {"event_type": "...", "event_message": "..."}}],
            "polling_fallback": "/tracking/orders/{order_id}/events",
        }
    }

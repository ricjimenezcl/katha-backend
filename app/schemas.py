from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class GeocodingResult(BaseModel):
    place_name: str
    text: str
    address: str
    center: list[float]
    relevance: float = 0.5
    place_type: list[str] = Field(default_factory=lambda: ["address"])


class GeocodingResponse(BaseModel):
    source: str
    results: list[GeocodingResult]


class ShippingRate(BaseModel):
    region_id: int
    region_name: str
    cost: int


class ShippingAddressPayload(BaseModel):
    display_name: str
    lat: str
    lon: str
    complement: str = ""
    region: str
    commune: str


class CartItemPayload(BaseModel):
    productId: int
    name: str
    price: int
    quantity: int


class CheckoutPayload(BaseModel):
    amount: int
    subtotal: int
    shippingCost: int
    currency: str
    items: list[CartItemPayload]
    shippingAddress: ShippingAddressPayload
    paymentMethod: str
    guestEmail: str | None = None


class OrderCreated(BaseModel):
    orderId: int
    transactionId: int


class TransbankInitResponse(BaseModel):
    url: str
    token: str
    orderId: int


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserMe(BaseModel):
    id: int
    email: str
    display_name: str | None
    role: str


# ── Products ──────────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str
    description: str | None = None
    price: int
    category: str
    image_url: str | None = None
    cloudinary_public_id: str | None = None
    stock: int = 0
    tag: str | None = None


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: int | None = None
    category: str | None = None
    image_url: str | None = None
    cloudinary_public_id: str | None = None
    stock: int | None = None
    active: bool | None = None
    tag: str | None = None


class CategoryResponse(BaseModel):
    id: int
    slug: str
    name: str
    sort_order: int = 0


class TallerResponse(BaseModel):
    id: int
    titulo: str
    descripcion: str
    horas: str
    nivel: str
    detalle: str
    icono: str
    sort_order: int
    active: bool


class TallerCreate(BaseModel):
    titulo: str
    descripcion: str
    horas: str
    nivel: str
    detalle: str
    icono: str = ""
    sort_order: int = 0
    active: bool = True


class TallerUpdate(BaseModel):
    titulo: str | None = None
    descripcion: str | None = None
    horas: str | None = None
    nivel: str | None = None
    detalle: str | None = None
    icono: str | None = None
    sort_order: int | None = None
    active: bool | None = None


class ProductResponse(BaseModel):
    id: int
    name: str
    material: str | None
    description: str | None
    price: int
    category: str
    image_url: str | None
    cloudinary_public_id: str | None
    stock: int
    active: bool
    tag: str | None
    created_at: datetime
    updated_at: datetime


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    total: int
    page: int
    limit: int


class ImageUploadResponse(BaseModel):
    url: str
    public_id: str


# ── Orders (admin) ────────────────────────────────────────────────────────────

class OrderItemDetail(BaseModel):
    id: int
    product_id: int
    product_name: str
    unit_price: int
    quantity: int
    subtotal: int
    image_url: str | None = None


class ShippingAddressDetail(BaseModel):
    display_name: str
    lat: float
    lon: float
    city: str | None
    region: str | None
    complement: str | None


class OrderDetail(BaseModel):
    id: int
    status: str
    payment_method: str
    subtotal: int
    shipping_cost: int
    total: int
    notes: str | None
    tracking_number: str | None
    shipping_carrier: str | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemDetail]
    shipping_address: ShippingAddressDetail | None


class OrderSummary(BaseModel):
    id: int
    status: str
    payment_method: str
    total: int
    shipping_cost: int
    tracking_number: str | None
    created_at: datetime


class OrderListResponse(BaseModel):
    items: list[OrderSummary]
    total: int
    page: int
    limit: int


class OrderStatusUpdate(BaseModel):
    status: str
    tracking_number: str | None = None
    shipping_carrier: str | None = None
    notes: str | None = None


# ── Inventory ─────────────────────────────────────────────────────────────────

class InventoryItem(BaseModel):
    id: int
    name: str
    category: str
    image_url: str | None
    stock: int
    stock_status: str  # 'ok' | 'low' | 'out'


class InventoryListResponse(BaseModel):
    items: list[InventoryItem]
    total: int


class StockAdjust(BaseModel):
    product_id: int
    quantity_change: int
    reason: str = "manual_adjustment"


class MovementRecord(BaseModel):
    id: int
    product_id: int
    product_name: str
    quantity_change: int
    reason: str
    created_at: datetime

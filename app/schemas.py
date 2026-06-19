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


class OrderCreated(BaseModel):
    orderId: int
    transactionId: int

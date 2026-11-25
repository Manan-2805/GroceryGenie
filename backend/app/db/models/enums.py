from enum import StrEnum


class UserRole(StrEnum):
    customer = "customer"
    seller = "seller"


class ChatMode(StrEnum):
    text = "text"
    voice = "voice"


class OrderStatus(StrEnum):
    placed = "placed"
    packed = "packed"
    out_for_delivery = "out_for_delivery"
    delivered = "delivered"


class FactCategory(StrEnum):
    dietary = "dietary"
    preference = "preference"
    instruction = "instruction"
    other = "other"

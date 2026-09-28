"""Typed caller library for the Bursawatch Discord Delivery Owner."""

DELIVERY_RECEIPT_WAIT_SECONDS = 10

from .client import DeliveryClient, DeliveryClientError
from .models import Attachment, DiscordQuery, OperationIntent, OperationReceipt

__all__ = [
    "Attachment",
    "DELIVERY_RECEIPT_WAIT_SECONDS",
    "DeliveryClient",
    "DeliveryClientError",
    "DiscordQuery",
    "OperationIntent",
    "OperationReceipt",
]

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BillingPlan:
    code: str
    name: str
    interval: str
    credits: int
    price_id: str | None


class InvalidWebhookSignature(ValueError):
    pass


def verify_paddle_signature(
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
    *,
    tolerance_seconds: int = 300,
    current_time: int | None = None,
) -> None:
    if not signature_header:
        raise InvalidWebhookSignature("Missing Paddle-Signature header")

    parts: dict[str, list[str]] = {}
    for item in signature_header.split(";"):
        key, separator, value = item.partition("=")
        if separator and key and value:
            parts.setdefault(key, []).append(value)

    timestamp_values = parts.get("ts", [])
    signatures = parts.get("h1", [])
    if not timestamp_values or not signatures:
        raise InvalidWebhookSignature("Malformed Paddle-Signature header")

    try:
        timestamp = int(timestamp_values[0])
    except ValueError as exc:
        raise InvalidWebhookSignature("Invalid webhook timestamp") from exc

    now = int(time.time()) if current_time is None else current_time
    if abs(now - timestamp) > tolerance_seconds:
        raise InvalidWebhookSignature("Webhook timestamp is outside the allowed window")

    signed_payload = str(timestamp).encode() + b":" + raw_body
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise InvalidWebhookSignature("Webhook signature does not match")


def parse_event(raw_body: bytes) -> dict[str, Any]:
    try:
        event = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Webhook body is not valid JSON") from exc
    if not isinstance(event, dict) or not event.get("event_id") or not event.get("event_type"):
        raise ValueError("Webhook event is missing its ID or type")
    return event


def first_price_id(data: dict[str, Any]) -> str | None:
    for item in data.get("items") or []:
        price = item.get("price") or {}
        price_id = price.get("id") or item.get("price_id")
        if price_id:
            return str(price_id)
    return None

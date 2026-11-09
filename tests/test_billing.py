import hashlib
import hmac
import importlib
import json
import time

from fastapi.testclient import TestClient

from app.billing import InvalidWebhookSignature, verify_paddle_signature
from app.repository import Repository


def paddle_signature(body: bytes, secret: str, timestamp: int) -> str:
    digest = hmac.new(
        secret.encode(),
        str(timestamp).encode() + b":" + body,
        hashlib.sha256,
    ).hexdigest()
    return f"ts={timestamp};h1={digest}"


def test_paddle_signature_verification_rejects_tampering():
    body = b'{"event_id":"evt_test"}'
    timestamp = 1_700_000_000
    signature = paddle_signature(body, "secret", timestamp)
    verify_paddle_signature(
        body,
        signature,
        "secret",
        current_time=timestamp,
    )
    try:
        verify_paddle_signature(
            body + b" ",
            signature,
            "secret",
            current_time=timestamp,
        )
    except InvalidWebhookSignature:
        pass
    else:
        raise AssertionError("Tampered webhook body should be rejected")


def test_paid_transaction_grants_credits_once(monkeypatch, tmp_path):
    secret = "pdl_test_webhook_secret"
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VOICEFORGE_PADDLE_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("VOICEFORGE_PADDLE_CLIENT_TOKEN", "test_client_token")
    monkeypatch.setenv("VOICEFORGE_PADDLE_CREATOR_MONTHLY_PRICE_ID", "pri_creator_monthly")
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    event = {
        "event_id": "evt_transaction_completed_1",
        "event_type": "transaction.completed",
        "occurred_at": "2026-11-09T12:00:00Z",
        "data": {
            "id": "txn_paid_1",
            "status": "completed",
            "customer_id": "ctm_customer_1",
            "subscription_id": "sub_customer_1",
            "custom_data": {"user_id": "paid-user", "plan_code": "creator_monthly"},
            "items": [{"price": {"id": "pri_creator_monthly"}, "quantity": 1}],
        },
    }
    body = json.dumps(event, separators=(",", ":")).encode()
    timestamp = int(time.time())
    headers = {
        "Paddle-Signature": paddle_signature(body, secret, timestamp),
        "Content-Type": "application/json",
    }

    with TestClient(module.app) as client:
        first = client.post("/api/billing/webhook", content=body, headers=headers)
        second = client.post("/api/billing/webhook", content=body, headers=headers)

    assert first.status_code == 200
    assert first.json()["applied"] is True
    assert second.status_code == 200
    assert second.json()["applied"] is False
    assert module.repository.balance("paid-user") == 105_000
    subscription = module.repository.get_subscription("paid-user")
    assert subscription["plan_code"] == "creator_monthly"
    assert subscription["status"] == "active"


def test_repository_can_mirror_subscription_without_granting_credits(tmp_path):
    repository = Repository(f"sqlite:///{(tmp_path / 'billing.db').as_posix()}", 0)
    applied = repository.apply_paddle_event(
        event_id="evt_subscription_update_1",
        event_type="subscription.updated",
        occurred_at="2026-11-09T12:00:00Z",
        user_id="user-1",
        subscription_id="sub_1",
        customer_id="ctm_1",
        price_id="pri_1",
        plan_code="pro_monthly",
        status="past_due",
        next_billed_at="2026-12-09T12:00:00Z",
        cancel_at_period_end=False,
    )
    assert applied is True
    assert repository.balance("user-1") == 0
    assert repository.get_subscription("user-1")["status"] == "past_due"

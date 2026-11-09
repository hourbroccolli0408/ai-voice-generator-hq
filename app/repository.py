from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CreditEntry(Base):
    __tablename__ = "credit_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(64))
    reference: Mapped[str] = mapped_column(String(160), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[str] = mapped_column(Text)


class BillingEvent(Base):
    __tablename__ = "billing_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    occurred_at: Mapped[str | None] = mapped_column(String(48), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Subscription(Base):
    __tablename__ = "subscriptions"

    paddle_subscription_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    paddle_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    price_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    next_billed_at: Mapped[str | None] = mapped_column(String(48), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


def utcnow() -> datetime:
    return datetime.now(UTC)


class InsufficientCredits(Exception):
    def __init__(self, balance: int, required: int) -> None:
        self.balance = balance
        self.required = required
        super().__init__(f"{required} credits required; {balance} available")


class Repository:
    def __init__(self, database_url: str, starter_credits: int) -> None:
        is_sqlite = database_url.startswith("sqlite")
        connect_args = (
            {"check_same_thread": False} if is_sqlite else {"connect_timeout": 10}
        )
        engine_options = {"connect_args": connect_args, "pool_pre_ping": True}
        if not is_sqlite:
            engine_options["pool_timeout"] = 10
        base_engine = create_engine(database_url, **engine_options)
        self._base_engine = base_engine
        self._schema_lock = threading.Lock()
        self._schema_ready = False
        if is_sqlite:
            self.engine = base_engine
            Base.metadata.create_all(self.engine)
            self._schema_ready = True
        else:
            self.engine = base_engine.execution_options(
                schema_translate_map={None: "voiceforge_private"}
            )
        self.starter_credits = starter_credits

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            # Supabase exposes the public schema through its Data API by default. Keep
            # authentication, jobs, and the credit ledger in an API-private schema.
            with self._base_engine.begin() as connection:
                schema_exists = connection.exec_driver_sql(
                    "SELECT 1 FROM pg_namespace WHERE nspname = 'voiceforge_private'"
                ).scalar()
                if not schema_exists:
                    connection.exec_driver_sql("CREATE SCHEMA voiceforge_private")
            Base.metadata.create_all(self.engine)
            self._schema_ready = True

    def _ensure_user(self, session: Session, user_id: str) -> None:
        user = session.get(User, user_id)
        if user:
            return
        session.add(User(id=user_id, created_at=utcnow()))
        session.flush()
        if self.starter_credits:
            session.add(
                CreditEntry(
                    user_id=user_id,
                    delta=self.starter_credits,
                    reason="starter_grant",
                    reference=f"starter:{user_id}",
                    created_at=utcnow(),
                )
            )

    @staticmethod
    def _balance(session: Session, user_id: str) -> int:
        value = session.scalar(
            select(func.coalesce(func.sum(CreditEntry.delta), 0)).where(
                CreditEntry.user_id == user_id
            )
        )
        return int(value or 0)

    def balance(self, user_id: str) -> int:
        self._ensure_schema()
        with Session(self.engine) as session, session.begin():
            self._ensure_user(session, user_id)
            return self._balance(session, user_id)

    def create_job_and_reserve(self, user_id: str, job: dict, credits: int) -> None:
        self._ensure_schema()
        with Session(self.engine) as session, session.begin():
            self._ensure_user(session, user_id)
            session.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one()
            balance = self._balance(session, user_id)
            if balance < credits:
                raise InsufficientCredits(balance, credits)
            session.add(
                CreditEntry(
                    user_id=user_id,
                    delta=-credits,
                    reason="generation_reservation",
                    reference=f"job:{job['id']}:reserve",
                    created_at=utcnow(),
                )
            )
            session.add(
                Job(
                    id=job["id"],
                    user_id=user_id,
                    status=job["status"],
                    created_at=datetime.fromisoformat(job["created_at"]),
                    payload=json.dumps(job),
                )
            )

    def update_job(self, job_id: str, **changes) -> dict:
        self._ensure_schema()
        with Session(self.engine) as session, session.begin():
            row = session.get(Job, job_id)
            if not row:
                raise KeyError(job_id)
            payload = json.loads(row.payload)
            payload.update(changes)
            row.status = payload["status"]
            row.payload = json.dumps(payload)
            return payload

    def get_job(self, job_id: str, user_id: str | None = None) -> dict | None:
        self._ensure_schema()
        with Session(self.engine) as session:
            row = session.get(Job, job_id)
            if not row or (user_id is not None and row.user_id != user_id):
                return None
            return json.loads(row.payload)

    def list_jobs(self, user_id: str, limit: int = 25) -> list[dict]:
        self._ensure_schema()
        with Session(self.engine) as session:
            rows = session.scalars(
                select(Job)
                .where(Job.user_id == user_id)
                .order_by(Job.created_at.desc())
                .limit(limit)
            ).all()
            return [json.loads(row.payload) for row in rows]

    def refund(self, user_id: str, job_id: str, credits: int) -> None:
        self._ensure_schema()
        try:
            with Session(self.engine) as session, session.begin():
                self._ensure_user(session, user_id)
                session.add(
                    CreditEntry(
                        user_id=user_id,
                        delta=credits,
                        reason="generation_refund",
                        reference=f"job:{job_id}:refund",
                        created_at=utcnow(),
                    )
                )
        except IntegrityError:
            # The unique reference makes retries and restarts safe.
            return

    def fail_incomplete_jobs(self) -> list[dict]:
        self._ensure_schema()
        failed: list[dict] = []
        with Session(self.engine) as session, session.begin():
            rows = session.scalars(select(Job).where(Job.status.in_(["queued", "processing"]))).all()
            for row in rows:
                payload = json.loads(row.payload)
                payload.update(
                    status="failed",
                    stage="Interrupted",
                    error="The service restarted before generation completed",
                    completed_at=utcnow().isoformat(),
                )
                row.status = "failed"
                row.payload = json.dumps(payload)
                payload["user_id"] = row.user_id
                failed.append(payload)
        return failed

    @staticmethod
    def _subscription_dict(row: Subscription | None) -> dict | None:
        if row is None:
            return None
        return {
            "id": row.paddle_subscription_id,
            "customer_id": row.paddle_customer_id,
            "price_id": row.price_id,
            "plan_code": row.plan_code,
            "status": row.status,
            "next_billed_at": row.next_billed_at,
            "cancel_at_period_end": row.cancel_at_period_end,
        }

    def get_subscription(self, user_id: str) -> dict | None:
        self._ensure_schema()
        with Session(self.engine) as session:
            row = session.scalar(
                select(Subscription)
                .where(Subscription.user_id == user_id)
                .order_by(Subscription.updated_at.desc())
                .limit(1)
            )
            return self._subscription_dict(row)

    def _upsert_subscription(
        self,
        session: Session,
        *,
        subscription_id: str,
        user_id: str,
        customer_id: str | None,
        price_id: str | None,
        plan_code: str | None,
        status: str,
        next_billed_at: str | None,
        cancel_at_period_end: bool,
    ) -> None:
        row = session.get(Subscription, subscription_id)
        if row is None:
            row = Subscription(
                paddle_subscription_id=subscription_id,
                user_id=user_id,
                paddle_customer_id=customer_id,
                price_id=price_id,
                plan_code=plan_code,
                status=status,
                next_billed_at=next_billed_at,
                cancel_at_period_end=cancel_at_period_end,
                updated_at=utcnow(),
            )
            session.add(row)
            return
        row.user_id = user_id
        row.paddle_customer_id = customer_id or row.paddle_customer_id
        row.price_id = price_id or row.price_id
        row.plan_code = plan_code or row.plan_code
        row.status = status
        row.next_billed_at = next_billed_at
        row.cancel_at_period_end = cancel_at_period_end
        row.updated_at = utcnow()

    def apply_paddle_event(
        self,
        *,
        event_id: str,
        event_type: str,
        occurred_at: str | None,
        user_id: str | None,
        transaction_id: str | None = None,
        subscription_id: str | None = None,
        customer_id: str | None = None,
        price_id: str | None = None,
        plan_code: str | None = None,
        status: str | None = None,
        next_billed_at: str | None = None,
        cancel_at_period_end: bool = False,
        credits: int = 0,
    ) -> bool:
        """Apply one verified Paddle event exactly once.

        The event record, subscription mirror, and any credit grant share one database
        transaction so a retry cannot partially or repeatedly provision an account.
        """
        self._ensure_schema()
        try:
            with Session(self.engine) as session, session.begin():
                if session.get(BillingEvent, event_id):
                    return False
                session.add(
                    BillingEvent(
                        event_id=event_id,
                        event_type=event_type,
                        occurred_at=occurred_at,
                        processed_at=utcnow(),
                    )
                )

                resolved_user_id = user_id
                if not resolved_user_id and subscription_id:
                    existing = session.get(Subscription, subscription_id)
                    resolved_user_id = existing.user_id if existing else None

                if resolved_user_id:
                    self._ensure_user(session, resolved_user_id)

                if credits > 0 and transaction_id and resolved_user_id:
                    session.add(
                        CreditEntry(
                            user_id=resolved_user_id,
                            delta=credits,
                            reason="subscription_payment",
                            reference=f"paddle:transaction:{transaction_id}",
                            created_at=utcnow(),
                        )
                    )

                if subscription_id and resolved_user_id:
                    self._upsert_subscription(
                        session,
                        subscription_id=subscription_id,
                        user_id=resolved_user_id,
                        customer_id=customer_id,
                        price_id=price_id,
                        plan_code=plan_code,
                        status=status or "active",
                        next_billed_at=next_billed_at,
                        cancel_at_period_end=cancel_at_period_end,
                    )
            return True
        except IntegrityError:
            # Paddle may retry the same transaction under another event ID. The unique
            # credit reference prevents a second allowance from being issued.
            return False

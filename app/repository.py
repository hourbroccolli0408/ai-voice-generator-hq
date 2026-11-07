from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine, func, select
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
        connect_args = {"check_same_thread": False} if is_sqlite else {}
        base_engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
        if is_sqlite:
            self.engine = base_engine
        else:
            # Supabase exposes the public schema through its Data API by default. Keep
            # authentication, jobs, and the credit ledger in an API-private schema.
            with base_engine.begin() as connection:
                connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS voiceforge_private")
            self.engine = base_engine.execution_options(
                schema_translate_map={None: "voiceforge_private"}
            )
        self.starter_credits = starter_credits
        Base.metadata.create_all(self.engine)

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
        with Session(self.engine) as session, session.begin():
            self._ensure_user(session, user_id)
            return self._balance(session, user_id)

    def create_job_and_reserve(self, user_id: str, job: dict, credits: int) -> None:
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
        with Session(self.engine) as session:
            row = session.get(Job, job_id)
            if not row or (user_id is not None and row.user_id != user_id):
                return None
            return json.loads(row.payload)

    def list_jobs(self, user_id: str, limit: int = 25) -> list[dict]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(Job)
                .where(Job.user_id == user_id)
                .order_by(Job.created_at.desc())
                .limit(limit)
            ).all()
            return [json.loads(row.payload) for row in rows]

    def refund(self, user_id: str, job_id: str, credits: int) -> None:
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

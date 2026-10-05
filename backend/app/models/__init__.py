from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(200), default="")
    soil_type: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Phase 10: optional, FARMER-PROVIDED context. All nullable: NULL means "not provided" (never guessed or defaulted).
    # Added to existing databases by database.migrate (ALTER TABLE ADD COLUMN, non-destructive).
    primary_crop: Mapped[str | None] = mapped_column(String(100), nullable=True)
    irrigation_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    season: Mapped[str | None] = mapped_column(String(20), nullable=True)
    planting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    context_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    crop: Mapped[str] = mapped_column(String(100))
    symptoms: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default="en")
    result_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Phase 2 (added to existing databases by database._migrate)
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_type: Mapped[str] = mapped_column(String(20), default="text", server_default="text")
    weather_json: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    weather_note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Phase 4: idempotent retries (scoped per user in queries; see routers/analyses.py)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Extra language versions of THIS check, {"en": result, "te": result}. The original result_json/language
    # are never modified. Added to existing databases by database.migrate (nullable, non-destructive).
    translations_json: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)

    # Phase 13: a check can be a REFINEMENT (answers to the quick questions) or a FOLLOW-UP of an earlier check.
    # Nullable, added to existing databases by database.migrate.
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    link_kind: Mapped[str | None] = mapped_column(String(12), nullable=True)

    farm: Mapped[Farm] = relationship(lazy="joined")


class FarmEvent(Base):
    """One entry in the farm diary: something the FARMER says they did (sowed, irrigated, sprayed ...). Never inferred."""

    __tablename__ = "farm_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    event_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


__all__ = ["User", "Farm", "Analysis", "FarmEvent"]

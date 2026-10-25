"""Persistence for the maintenance hold (#61)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

SINGLETON_ID = 1


class MaintenanceControlRow(Base):
    """Exactly one row, seeded by the migration and never inserted again."""

    __tablename__ = "maintenance_control"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_maintenance_control_singleton"),
        CheckConstraint("phase IN ('normal', 'maintenance')", name="ck_maintenance_control_phase"),
        CheckConstraint("epoch >= 0", name="ck_maintenance_control_epoch"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    admission_closed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_return_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    changed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

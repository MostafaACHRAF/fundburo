from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (
        CheckConstraint("role in ('reporter','claimer')", name="app_user_role_check"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    items: Mapped[list["Item"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Item(Base):
    __tablename__ = "item"
    __table_args__ = (
        CheckConstraint("item_type in ('lost','found')", name="item_item_type_check"),
        CheckConstraint(
            "status in ('active','matched','expired')", name="item_status_check"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str | None] = mapped_column(Text)
    size: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[str | None] = mapped_column(Text)
    address_text: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feel: Mapped[str | None] = mapped_column(Text)
    smell: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now() + interval '10 days'"),
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )

    user: Mapped[AppUser] = relationship(back_populates="items")
    lost_matches: Mapped[list["ItemMatch"]] = relationship(
        foreign_keys="ItemMatch.lost_item_id",
        back_populates="lost_item",
        cascade="all, delete-orphan",
    )
    found_matches: Mapped[list["ItemMatch"]] = relationship(
        foreign_keys="ItemMatch.found_item_id",
        back_populates="found_item",
        cascade="all, delete-orphan",
    )


class ItemMatch(Base):
    __tablename__ = "item_match"
    __table_args__ = (
        CheckConstraint("score >= 0 and score <= 1", name="item_match_score_check"),
        CheckConstraint(
            "confidence in ('high','medium','low')",
            name="item_match_confidence_check",
        ),
        UniqueConstraint("lost_item_id", "found_item_id", name="uq_lost_found_pair"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lost_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("item.id", ondelete="CASCADE"), nullable=False
    )
    found_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("item.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    lost_item: Mapped[Item] = relationship(
        foreign_keys=[lost_item_id], back_populates="lost_matches"
    )
    found_item: Mapped[Item] = relationship(
        foreign_keys=[found_item_id], back_populates="found_matches"
    )

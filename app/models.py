"""Локальное состояние обёртки.

Keitaro — источник правды о том, что опубликовано. В нашей базе хранится:
- черновик (status/share/pinned), который пользователь меняет кнопками;
- снимок опубликованного состояния (pub_status/pub_share) — то, что было
  в Keitaro после последнего Fetch или Push. По разнице черновика и снимка
  считаем «жёлтый» (неопубликованный) поток и умеем откатывать Cancel;
- архив: офферы, которых больше нет в Keitaro, остаются со статусом removed,
  чтобы их можно было вернуть кнопкой Bring back.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

ACTIVE = "active"
REMOVED = "removed"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str | None] = mapped_column(String(64))
    # Заполняются, только если кампанию создал наш создаватор.
    geo: Mapped[str | None] = mapped_column(String(255))
    offer_id: Mapped[int | None] = mapped_column(Integer)
    domain_id: Mapped[int | None] = mapped_column(Integer)
    group_id: Mapped[int | None] = mapped_column(Integer)
    traffic_source_id: Mapped[int | None] = mapped_column(Integer)
    created_by_wrapper: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    streams: Mapped[list["Stream"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="Stream.position",
    )


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), default="")
    type: Mapped[str | None] = mapped_column(String(32))
    schema: Mapped[str | None] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str | None] = mapped_column(String(32))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[Campaign] = relationship(back_populates="streams")
    offers: Mapped[list["StreamOffer"]] = relationship(
        back_populates="stream",
        cascade="all, delete-orphan",
        order_by="StreamOffer.position",
    )


class StreamOffer(Base):
    """Привязка оффера к потоку: черновик + опубликованный снимок."""

    __tablename__ = "stream_offers"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id", name="uq_stream_offer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int] = mapped_column(Integer)  # ID оффера в Keitaro
    offer_name: Mapped[str] = mapped_column(String(255), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)

    # Черновик.
    status: Mapped[str] = mapped_column(String(16), default=ACTIVE)
    share: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    # Опубликованное состояние. pub_status = None — оффер добавлен в обёртке
    # и ещё ни разу не публиковался (Cancel такую привязку удаляет).
    pub_status: Mapped[str | None] = mapped_column(String(16))
    pub_share: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    stream: Mapped[Stream] = relationship(back_populates="offers")

    @property
    def is_dirty(self) -> bool:
        was_active = self.pub_status == ACTIVE
        is_active = self.status == ACTIVE
        return was_active != is_active or (is_active and self.share != self.pub_share)

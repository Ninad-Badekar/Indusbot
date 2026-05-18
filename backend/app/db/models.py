import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Enum as SAEnum, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

import enum

from app.db.database import Base


class CallStatus(str, enum.Enum):
    ringing = "ringing"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    call_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[CallStatus] = mapped_column(SAEnum(CallStatus), default=CallStatus.in_progress)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    transcripts: Mapped[list["Transcript"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="transcripts")

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    credentials = relationship(
        "CloudCredential", back_populates="user", cascade="all, delete-orphan"
    )


class CloudCredential(Base):
    __tablename__ = "cloud_credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider = Column(String(20), nullable=False)  # aws / gcp / azure
    label = Column(String(255), nullable=False)
    encrypted_data = Column(Text, nullable=False)  # Fernet-encrypted JSON blob
    region = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "label", name="uq_user_label"),
    )

    user = relationship("User", back_populates="credentials")

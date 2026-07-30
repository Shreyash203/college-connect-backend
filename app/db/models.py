from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Table
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

profile_interests = Table(
    "profile_interests",
    Base.metadata,
    Column("profile_id", ForeignKey("student_profiles.id"), primary_key=True),
    Column("interest_id", ForeignKey("interests.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def is_admin(self) -> bool:
        from app.core.config import settings
        return self.email.lower() in settings.admin_emails_list

    profile = relationship("StudentProfile", back_populates="user", uselist=False)


class StudentProfile(Base):
    image_url = Column(String, nullable=True)  # URL to Azure Blob image
    __tablename__ = "student_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    display_name = Column(String(255), nullable=True)
    department = Column(String(100), nullable=True)
    year = Column(String(50), nullable=True)
    bio = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="profile")
    interests = relationship("Interest", secondary=profile_interests, back_populates="profiles")


class Interest(Base):
    __tablename__ = "interests"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    profiles = relationship("StudentProfile", secondary=profile_interests, back_populates="interests")


class MarketplaceItem(Base):
    __tablename__ = "marketplace_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    image_url = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", backref="marketplace_items")


class MarketplaceInterest(Base):
    __tablename__ = "marketplace_interests"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    item_id = Column(Integer, ForeignKey("marketplace_items.id"), primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
class Confession(Base):
    __tablename__ = "confessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    college_domain = Column(String(255), nullable=False)
    content = Column(String(1000), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", backref="confessions")


class ConfessionLike(Base):
    __tablename__ = "confession_likes"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    confession_id = Column(Integer, ForeignKey("confessions.id"), primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
class StudentApp(Base):
    __tablename__ = "student_apps"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    app_name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=False)
    app_url = Column(String(255), nullable=True)
    college_domain = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", backref="student_apps")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(String(1000), nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", backref="notifications")

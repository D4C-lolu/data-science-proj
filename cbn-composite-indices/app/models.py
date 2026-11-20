from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    username = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())

    index_runs = db.relationship(
        "IndexRun",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class IndexRun(db.Model):
    __tablename__ = "index_runs"
    __table_args__ = (
        CheckConstraint(
            "index_type IN ('BCI', 'CCI', 'HFCI', 'IPI', 'LMCI')",
            name="ck_index_runs_index_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_index_runs_status",
        ),
        Index("ix_index_runs_user_id", "user_id"),
        Index("ix_index_runs_status", "status"),
        Index("ix_index_runs_created_at", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", name="fk_index_runs_user_id_users", ondelete="CASCADE"),
        nullable=False,
    )
    index_type = db.Column(db.String(8), nullable=False)
    status = db.Column(db.String(16), nullable=False, server_default="queued")
    original_filename = db.Column(db.String(255), nullable=False)
    upload_key = db.Column(db.String(255), nullable=False, unique=True)
    result_key = db.Column(db.String(255), nullable=True, unique=True)
    result_metadata = db.Column(db.JSON().with_variant(JSONB, "postgresql"), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", back_populates="index_runs")

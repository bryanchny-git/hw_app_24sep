from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

LEAVE_TYPES = ["annual", "medical", "unpaid"]
ANNUAL_ENTITLEMENT_DAYS = 14
MEDICAL_ENTITLEMENT_DAYS = 14
MAX_ANNUAL_CARRY_FORWARD = 5


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, default="")
    role = db.Column(db.String(20), nullable=False)  # "employee" or "manager"
    manager_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    manager = db.relationship("User", remote_side=[id], backref="reports")

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_manager(self):
        return self.role == "manager"


class LeaveEntitlement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    leave_type = db.Column(db.String(20), nullable=False)
    entitlement_days = db.Column(db.Integer, nullable=True)  # None = uncapped (unpaid)
    carried_forward_days = db.Column(db.Integer, nullable=False, default=0)

    user = db.relationship("User", backref="entitlements")

    __table_args__ = (
        db.UniqueConstraint("user_id", "year", "leave_type", name="uq_entitlement"),
    )


class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    leave_type = db.Column(db.String(20), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    working_days = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    reason = db.Column(db.String(500), nullable=True)
    manager_comment = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    decided_at = db.Column(db.DateTime, nullable=True)
    decided_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    user = db.relationship("User", foreign_keys=[user_id], backref="leave_requests")
    decider = db.relationship("User", foreign_keys=[decided_by])


class Notification(db.Model):
    """A simulated email: logged to the console and stored here instead of actually
    being sent, since this app has no SMTP credentials configured."""

    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    recipient = db.relationship("User", foreign_keys=[recipient_id])

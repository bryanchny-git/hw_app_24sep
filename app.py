import calendar
import os
from datetime import date, datetime

import click
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)

from leave_logic import (
    approved_days_taken,
    count_working_days,
    get_or_create_entitlement,
    pending_days,
    remaining_balance,
    rollover_year,
)
from models import (
    ANNUAL_ENTITLEMENT_DAYS,
    LEAVE_TYPES,
    LeaveRequest,
    MEDICAL_ENTITLEMENT_DAYS,
    Notification,
    User,
    db,
)
from notifications import notify_decision, notify_submission

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_DAYS_BY_TYPE = {
    "annual": ANNUAL_ENTITLEMENT_DAYS,
    "medical": MEDICAL_ENTITLEMENT_DAYS,
    "unpaid": None,
}


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "dev-secret-key-change-in-production"
    )

    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        # Vercel/Neon/Render Postgres URLs commonly use the "postgres://" scheme,
        # but SQLAlchemy's psycopg driver requires "postgresql://".
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    else:
        # Local dev fallback: a SQLite file next to this script. Not usable on
        # Vercel, whose filesystem is read-only outside /tmp — set DATABASE_URL
        # there to point at a real Postgres database instead.
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
            BASE_DIR, "leave.db"
        )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    register_routes(app)
    register_cli(app)
    return app


def register_routes(app):
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username).first()
            if user is None or not user.check_password(password):
                flash("Invalid username or password.", "error")
                return render_template("login.html")
            login_user(user)
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        if current_user.is_manager:
            return redirect(url_for("manager_queue"))

        year = date.today().year
        balances = []
        for leave_type in LEAVE_TYPES:
            default_days = DEFAULT_DAYS_BY_TYPE[leave_type]
            entitlement = get_or_create_entitlement(
                current_user.id, year, leave_type, default_days
            )
            db.session.commit()
            taken = approved_days_taken(current_user.id, year, leave_type)
            pending = pending_days(current_user.id, year, leave_type)
            remaining = remaining_balance(entitlement, taken)
            balances.append(
                {
                    "leave_type": leave_type,
                    "entitlement": entitlement.entitlement_days,
                    "carried_forward": entitlement.carried_forward_days,
                    "taken": taken,
                    "pending": pending,
                    "remaining": remaining,
                }
            )

        my_requests = (
            LeaveRequest.query.filter_by(user_id=current_user.id)
            .order_by(LeaveRequest.created_at.desc())
            .all()
        )
        return render_template(
            "dashboard.html", balances=balances, my_requests=my_requests, year=year
        )

    @app.route("/apply", methods=["POST"])
    @login_required
    def apply():
        if current_user.is_manager:
            abort(403)

        leave_type = request.form.get("leave_type")
        start_str = request.form.get("start_date")
        end_str = request.form.get("end_date")
        reason = request.form.get("reason", "").strip()

        if leave_type not in LEAVE_TYPES:
            flash("Please choose a valid leave type.", "error")
            return redirect(url_for("dashboard"))

        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            flash("Please provide valid start and end dates.", "error")
            return redirect(url_for("dashboard"))

        if end_date < start_date:
            flash("End date cannot be before start date.", "error")
            return redirect(url_for("dashboard"))

        working_days = count_working_days(start_date, end_date)
        if working_days == 0:
            flash("Selected range has no working days.", "error")
            return redirect(url_for("dashboard"))

        year = start_date.year
        default_days = DEFAULT_DAYS_BY_TYPE[leave_type]
        entitlement = get_or_create_entitlement(
            current_user.id, year, leave_type, default_days
        )
        db.session.commit()

        if entitlement.entitlement_days is not None:
            taken = approved_days_taken(current_user.id, year, leave_type)
            already_pending = pending_days(current_user.id, year, leave_type)
            remaining = remaining_balance(entitlement, taken + already_pending)
            if remaining is not None and working_days > remaining:
                flash(
                    f"Not enough {leave_type} balance remaining "
                    f"({remaining} day(s) left, requested {working_days}).",
                    "error",
                )
                return redirect(url_for("dashboard"))

        leave_request = LeaveRequest(
            user_id=current_user.id,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            working_days=working_days,
            status="pending",
            reason=reason or None,
        )
        db.session.add(leave_request)
        db.session.commit()
        notify_submission(leave_request)
        flash("Leave request submitted.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/manager/queue")
    @login_required
    def manager_queue():
        if not current_user.is_manager:
            abort(403)
        pending_requests = (
            LeaveRequest.query.join(User, LeaveRequest.user_id == User.id)
            .filter(User.manager_id == current_user.id, LeaveRequest.status == "pending")
            .order_by(LeaveRequest.created_at.asc())
            .all()
        )
        decided_requests = (
            LeaveRequest.query.join(User, LeaveRequest.user_id == User.id)
            .filter(User.manager_id == current_user.id, LeaveRequest.status != "pending")
            .order_by(LeaveRequest.decided_at.desc())
            .limit(20)
            .all()
        )
        return render_template(
            "manager_queue.html",
            pending_requests=pending_requests,
            decided_requests=decided_requests,
        )

    @app.route("/manager/decide/<int:request_id>", methods=["POST"])
    @login_required
    def manager_decide(request_id):
        if not current_user.is_manager:
            abort(403)
        leave_request = db.session.get(LeaveRequest, request_id)
        if leave_request is None or leave_request.user.manager_id != current_user.id:
            abort(404)
        if leave_request.status != "pending":
            flash("This request has already been decided.", "error")
            return redirect(url_for("manager_queue"))

        decision = request.form.get("decision")
        comment = request.form.get("comment", "").strip()
        if decision not in ("approved", "rejected"):
            flash("Invalid decision.", "error")
            return redirect(url_for("manager_queue"))

        leave_request.status = decision
        leave_request.manager_comment = comment or None
        leave_request.decided_at = datetime.utcnow()
        leave_request.decided_by = current_user.id
        db.session.commit()
        notify_decision(leave_request)
        flash(f"Request {decision}.", "success")
        return redirect(url_for("manager_queue"))

    @app.route("/calendar")
    @login_required
    def team_calendar():
        today = date.today()
        year = request.args.get("year", today.year, type=int)
        month = request.args.get("month", today.month, type=int)

        if current_user.is_manager:
            team_ids = [u.id for u in User.query.filter_by(manager_id=current_user.id)]
        else:
            team_ids = [current_user.id]
            if current_user.manager_id:
                team_ids += [
                    u.id
                    for u in User.query.filter_by(manager_id=current_user.manager_id)
                ]
            team_ids = list(set(team_ids))

        approved = LeaveRequest.query.filter(
            LeaveRequest.user_id.in_(team_ids), LeaveRequest.status == "approved"
        ).all()

        cal = calendar.Calendar(firstweekday=0)
        weeks = cal.monthdayscalendar(year, month)

        day_entries = {}
        for req in approved:
            d = req.start_date
            while d <= req.end_date:
                if d.year == year and d.month == month and d.weekday() < 5:
                    day_entries.setdefault(d.day, []).append(req.user.full_name)
                d = date.fromordinal(d.toordinal() + 1)

        prev_month = month - 1 or 12
        prev_year = year - 1 if month == 1 else year
        next_month = month + 1 if month < 12 else 1
        next_year = year + 1 if month == 12 else year

        return render_template(
            "calendar.html",
            weeks=weeks,
            day_entries=day_entries,
            year=year,
            month=month,
            month_name=calendar.month_name[month],
            prev_year=prev_year,
            prev_month=prev_month,
            next_year=next_year,
            next_month=next_month,
        )

    @app.route("/notifications")
    @login_required
    def notifications():
        my_notifications = (
            Notification.query.filter_by(recipient_id=current_user.id)
            .order_by(Notification.created_at.desc())
            .all()
        )
        return render_template("notifications.html", notifications=my_notifications)


def register_cli(app):
    @app.cli.command("rollover-year")
    @click.argument("from_year", type=int)
    @click.argument("to_year", type=int)
    def rollover_year_command(from_year, to_year):
        with app.app_context():
            created = rollover_year(from_year, to_year)
            click.echo(f"Created {len(created)} entitlement rows for {to_year}.")


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)

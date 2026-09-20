from datetime import timedelta

from models import LeaveEntitlement, LeaveRequest, MAX_ANNUAL_CARRY_FORWARD, db


def count_working_days(start_date, end_date):
    """Weekday count between start_date and end_date, inclusive. No holiday calendar."""
    days = 0
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # Mon-Fri
            days += 1
        current += timedelta(days=1)
    return days


def get_or_create_entitlement(user_id, year, leave_type, default_days):
    entitlement = LeaveEntitlement.query.filter_by(
        user_id=user_id, year=year, leave_type=leave_type
    ).first()
    if entitlement is None:
        entitlement = LeaveEntitlement(
            user_id=user_id,
            year=year,
            leave_type=leave_type,
            entitlement_days=default_days,
            carried_forward_days=0,
        )
        db.session.add(entitlement)
        db.session.flush()
    return entitlement


def approved_days_taken(user_id, year, leave_type):
    requests = LeaveRequest.query.filter_by(
        user_id=user_id, leave_type=leave_type, status="approved"
    ).all()
    return sum(r.working_days for r in requests if r.start_date.year == year)


def pending_days(user_id, year, leave_type):
    requests = LeaveRequest.query.filter_by(
        user_id=user_id, leave_type=leave_type, status="pending"
    ).all()
    return sum(r.working_days for r in requests if r.start_date.year == year)


def remaining_balance(entitlement, taken_days):
    if entitlement.entitlement_days is None:
        return None  # uncapped (unpaid)
    total_allowance = entitlement.entitlement_days + entitlement.carried_forward_days
    return total_allowance - taken_days


def rollover_year(from_year, to_year):
    """Create next year's entitlement rows, carrying forward up to
    MAX_ANNUAL_CARRY_FORWARD unused annual days. Medical/unpaid do not carry."""
    from models import User, ANNUAL_ENTITLEMENT_DAYS, MEDICAL_ENTITLEMENT_DAYS

    created = []
    for user in User.query.all():
        annual_entitlement = LeaveEntitlement.query.filter_by(
            user_id=user.id, year=from_year, leave_type="annual"
        ).first()
        unused_annual = 0
        if annual_entitlement is not None:
            taken = approved_days_taken(user.id, from_year, "annual")
            remaining = remaining_balance(annual_entitlement, taken)
            unused_annual = max(remaining or 0, 0)
        carry_forward = min(unused_annual, MAX_ANNUAL_CARRY_FORWARD)

        for leave_type, default_days, carry in (
            ("annual", ANNUAL_ENTITLEMENT_DAYS, carry_forward),
            ("medical", MEDICAL_ENTITLEMENT_DAYS, 0),
            ("unpaid", None, 0),
        ):
            existing = LeaveEntitlement.query.filter_by(
                user_id=user.id, year=to_year, leave_type=leave_type
            ).first()
            if existing is not None:
                continue
            entitlement = LeaveEntitlement(
                user_id=user.id,
                year=to_year,
                leave_type=leave_type,
                entitlement_days=default_days,
                carried_forward_days=carry,
            )
            db.session.add(entitlement)
            created.append(entitlement)
    db.session.commit()
    return created

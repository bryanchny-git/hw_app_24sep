"""Creates leave.db and seeds sample accounts. Safe to re-run (skips if data exists)."""

from datetime import date

from app import create_app
from models import ANNUAL_ENTITLEMENT_DAYS, LeaveEntitlement, MEDICAL_ENTITLEMENT_DAYS, User, db

SAMPLE_PASSWORD = "password"


def seed():
    app = create_app()
    with app.app_context():
        db.create_all()

        if User.query.first() is not None:
            print("Database already has users; skipping seed.")
            return

        manager = User(
            username="manager1",
            full_name="Morgan Lee",
            email="manager1@example.com",
            role="manager",
        )
        manager.set_password(SAMPLE_PASSWORD)
        db.session.add(manager)
        db.session.flush()

        employees = [
            User(
                username="emp1",
                full_name="Alex Chen",
                email="emp1@example.com",
                role="employee",
                manager_id=manager.id,
            ),
            User(
                username="emp2",
                full_name="Jordan Patel",
                email="emp2@example.com",
                role="employee",
                manager_id=manager.id,
            ),
            User(
                username="emp3",
                full_name="Sam Rivera",
                email="emp3@example.com",
                role="employee",
                manager_id=manager.id,
            ),
        ]
        for employee in employees:
            employee.set_password(SAMPLE_PASSWORD)
            db.session.add(employee)
        db.session.flush()

        year = date.today().year
        for user in [manager] + employees:
            db.session.add(
                LeaveEntitlement(
                    user_id=user.id,
                    year=year,
                    leave_type="annual",
                    entitlement_days=ANNUAL_ENTITLEMENT_DAYS,
                    carried_forward_days=0,
                )
            )
            db.session.add(
                LeaveEntitlement(
                    user_id=user.id,
                    year=year,
                    leave_type="medical",
                    entitlement_days=MEDICAL_ENTITLEMENT_DAYS,
                    carried_forward_days=0,
                )
            )
            db.session.add(
                LeaveEntitlement(
                    user_id=user.id,
                    year=year,
                    leave_type="unpaid",
                    entitlement_days=None,
                    carried_forward_days=0,
                )
            )

        db.session.commit()
        print("Seeded database with sample accounts (all passwords: 'password'):")
        print("  manager1 (manager) -> Morgan Lee")
        print("  emp1, emp2, emp3 (employees, report to manager1)")


if __name__ == "__main__":
    seed()

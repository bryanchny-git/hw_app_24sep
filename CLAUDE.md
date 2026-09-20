# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project

A leave management web app: employees apply for annual/medical/unpaid leave, managers approve or
reject with a comment. Flask + SQLAlchemy + SQLite backend, server-rendered Jinja2 templates
(no JS framework, no build step).

## Running it

```
pip install -r requirements.txt
python seed.py        # creates leave.db and seeds sample accounts (idempotent)
python app.py          # runs the dev server on http://127.0.0.1:5000
```

Sample accounts (password `password` for all): `manager1` (manager), `emp1`/`emp2`/`emp3`
(employees reporting to `manager1`).

There is no automated test suite; verify manually by logging in as an employee and a manager.

## Architecture

- `models.py` — SQLAlchemy models: `User` (role `employee`/`manager`, self-referential
  `manager_id`, `email`), `LeaveEntitlement` (per user/year/leave_type; `entitlement_days=None`
  means uncapped, used for unpaid leave), `LeaveRequest` (status `pending`/`approved`/`rejected`),
  `Notification` (a simulated email logged for a recipient — see `notifications.py`).
- `leave_logic.py` — pure business logic, kept separate from routes so it's testable without a
  request context: `count_working_days` (weekday count, no holiday calendar),
  `get_or_create_entitlement` (lazily creates the current year's entitlement row on first use),
  `approved_days_taken`/`pending_days`, `remaining_balance`, and `rollover_year` (carries forward
  up to `MAX_ANNUAL_CARRY_FORWARD` unused annual days into next year; medical/unpaid never carry).
- `notifications.py` — simulated email: `send_email()` prints to the console and writes a
  `Notification` row instead of using real SMTP (no mail credentials are configured).
  `notify_submission()` emails the employee's manager when a request is created;
  `notify_decision()` emails the employee when their request is approved/rejected. Both are called
  from `app.py` right after the relevant `db.session.commit()`.
- `app.py` — `create_app()` factory wires Flask-SQLAlchemy and Flask-Login; routes are registered
  in `register_routes()`. Key routes: `/` (employee dashboard — redirects managers to
  `/manager/queue`), `/apply` (POST, creates a pending `LeaveRequest`, checks remaining balance
  for annual/medical before allowing it, then calls `notify_submission`), `/manager/queue` +
  `/manager/decide/<id>` (managers only see/act on requests from employees where
  `User.manager_id == current_user.id`; deciding calls `notify_decision`), `/calendar` (month grid
  of approved leave; a day with 2+ people out is flagged as an overlap), `/notifications` (lists
  the current user's `Notification` rows — the in-app inbox for simulated emails).
- CLI command `flask --app app rollover-year <from_year> <to_year>` runs the yearly carry-forward
  (registered in `register_cli()`); it's a manual/cron-triggered command, not automatic.
- `seed.py` — creates the DB (`db.create_all()`) and seeds one manager + three employees with
  current-year entitlements. Skips seeding if any `User` row already exists, so it's safe to
  re-run.
- `templates/` — `base.html` has the shared nav/flash-message layout; `dashboard.html`
  (employee balance cards + apply form + request history), `manager_queue.html` (pending queue +
  recent decisions), `calendar.html` (month grid, `day_entries` maps day-of-month to a list of
  employee names on leave that day), `notifications.html` (the simulated-email inbox).
- `static/style.css` — all styling, plain CSS custom properties on `:root` (no dark mode, unlike
  the sibling `ToDo` project).

## Known limitations (by design, out of scope for this version)

- Email is simulated, not real — no SMTP is configured, so "emails" only ever appear in the
  server console and each recipient's `/notifications` page. Wiring up real sending (e.g.
  Flask-Mail) would mean replacing `send_email()` in `notifications.py` and adding SMTP
  credentials via environment variables.
- `leave.db` (SQLite) is a single local file — fine for local/demo use, not concurrent-safe for
  production traffic.
- No holiday calendar — working-day counts only exclude Saturday/Sunday.
- No self-signup or admin UI for creating users — accounts come from `seed.py` only.

"""Simulated email notifications: no SMTP is configured, so 'sending' an email means
printing it to the console and storing it as a Notification row the recipient can read
in-app at /notifications."""

from models import Notification, db


def send_email(recipient, subject, body):
    print(f"--- EMAIL to {recipient.email} ---\nSubject: {subject}\n{body}\n---")
    db.session.add(
        Notification(recipient_id=recipient.id, subject=subject, body=body)
    )
    db.session.commit()


def notify_submission(leave_request):
    manager = leave_request.user.manager
    if manager is None:
        return
    subject = f"New {leave_request.leave_type} leave request from {leave_request.user.full_name}"
    body = (
        f"{leave_request.user.full_name} requested {leave_request.leave_type} leave "
        f"from {leave_request.start_date} to {leave_request.end_date} "
        f"({leave_request.working_days} working day(s)).\n"
        f"Reason: {leave_request.reason or '-'}\n"
        f"Review it at /manager/queue."
    )
    send_email(manager, subject, body)


def notify_decision(leave_request):
    employee = leave_request.user
    subject = f"Your {leave_request.leave_type} leave request was {leave_request.status}"
    body = (
        f"Your {leave_request.leave_type} leave request from {leave_request.start_date} "
        f"to {leave_request.end_date} was {leave_request.status} by "
        f"{leave_request.decider.full_name if leave_request.decider else 'your manager'}.\n"
        f"Comment: {leave_request.manager_comment or '-'}"
    )
    send_email(employee, subject, body)

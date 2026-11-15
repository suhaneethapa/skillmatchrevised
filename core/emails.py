"""
SkillMatch - Email Notification Service
=======================================
Provides plain-text transactional email notifications for all application
and listing lifecycle transitions.

Features:
- Academic, restrained plain-text emails.
- Dispatched safely post-transaction via `transaction.on_commit`.
- Email send failures are logged and never roll back DB operations.
- Defaults to Django console backend for local presentation.
"""

import logging
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

logger = logging.getLogger(__name__)

EMAIL_HEADER = """SkillMatch Internship Placement System
======================================
"""

EMAIL_FOOTER = """
--------------------------------------
This is an automated academic notification from SkillMatch.
Do not reply directly to this email.
"""


def _send_email_safe(recipient_email, subject, body):
    """
    Direct low-level email sender. Catches all exceptions to prevent
    application workflow failures.
    """
    if not recipient_email:
        return

    full_subject = f"[SkillMatch] {subject}"
    full_body = f"{EMAIL_HEADER}\n{body}\n{EMAIL_FOOTER}"
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "SkillMatch <noreply@skillmatch.local>")

    try:
        send_mail(
            subject=full_subject,
            message=full_body,
            from_email=from_email,
            recipient_list=[recipient_email],
            fail_silently=False,
        )
    except Exception as exc:
        logger.error("Failed sending email '%s' to %s: %s", subject, recipient_email, exc)


def send_notification_email(recipient_email, subject, body):
    """
    Queues plain-text email to be sent after the active DB transaction commits.
    If called outside an active transaction, dispatches immediately.
    """
    def task():
        _send_email_safe(recipient_email, subject, body)

    try:
        connection = transaction.get_connection()
        if connection.in_atomic_block:
            transaction.on_commit(task)
        else:
            task()
    except Exception:
        # Fallback if transaction hooks fail
        task()


def notify_application_submitted(application):
    """
    Notifies the student that their application was recorded,
    and notifies the employer about the new applicant.
    """
    student_email = application.student.email
    company_email = application.internship.company.user.email
    internship_title = application.internship.title
    company_name = application.internship.company.organization_name

    # Student confirmation
    student_body = (
        f"Dear Student,\n\n"
        f"Your application for the following position has been received:\n"
        f"- Position: {internship_title}\n"
        f"- Organization: {company_name}\n"
        f"- Match Score: {application.match_score}%\n\n"
        f"You can monitor the status of your application from your student dashboard."
    )
    send_notification_email(student_email, f"Application Received: {internship_title}", student_body)

    # Company notification
    company_body = (
        f"Dear {company_name},\n\n"
        f"A new candidate has submitted an application for your listing:\n"
        f"- Position: {internship_title}\n"
        f"- Candidate Email: {student_email}\n"
        f"- Match Score: {application.match_score}%\n\n"
        f"Please log in to your company dashboard to review the applicant's profile and CV."
    )
    send_notification_email(company_email, f"New Applicant: {internship_title}", company_body)


def notify_offer_issued(application):
    """
    Notifies student that an offer has been issued for their application.
    """
    student_email = application.student.email
    internship_title = application.internship.title
    company_name = application.internship.company.organization_name

    body = (
        f"Dear Student,\n\n"
        f"Congratulations! {company_name} has issued an internship offer for:\n"
        f"- Position: {internship_title}\n\n"
        f"Please sign in to your SkillMatch account and visit your dashboard to review "
        f"the offer details and accept or decline."
    )
    send_notification_email(student_email, f"Internship Offer: {internship_title}", body)


def notify_offer_accepted(application):
    """
    Notifies employer that the student accepted the offer,
    and sends confirmation to the student.
    """
    student_email = application.student.email
    company_email = application.internship.company.user.email
    internship_title = application.internship.title
    company_name = application.internship.company.organization_name

    # Employer notification
    company_body = (
        f"Dear {company_name},\n\n"
        f"Candidate {student_email} has accepted your internship offer for:\n"
        f"- Position: {internship_title}\n\n"
        f"The candidate is now confirmed for placement."
    )
    send_notification_email(company_email, f"Offer Accepted: {internship_title}", company_body)

    # Student confirmation
    student_body = (
        f"Dear Student,\n\n"
        f"You have successfully accepted the internship offer for:\n"
        f"- Position: {internship_title}\n"
        f"- Organization: {company_name}\n\n"
        f"You may now track your placement and weekly journal entries from your dashboard."
    )
    send_notification_email(student_email, f"Offer Accepted: {internship_title}", student_body)


def notify_offer_declined(application):
    """
    Notifies employer that the candidate declined the offer.
    """
    student_email = application.student.email
    company_email = application.internship.company.user.email
    internship_title = application.internship.title
    company_name = application.internship.company.organization_name

    body = (
        f"Dear {company_name},\n\n"
        f"Candidate {student_email} has declined the internship offer for:\n"
        f"- Position: {internship_title}\n\n"
        f"You may review other candidates from your applicants dashboard."
    )
    send_notification_email(company_email, f"Offer Declined: {internship_title}", body)


def notify_application_rejected(application, reason="", feedback=""):
    """
    Notifies candidate that their application was rejected by the company.
    """
    student_email = application.student.email
    internship_title = application.internship.title
    company_name = application.internship.company.organization_name

    reason_val = reason or getattr(application, 'rejection_reason', '')
    feedback_val = feedback or getattr(application, 'rejection_feedback', '')

    reason_text = f"Reason: {reason_val}\n" if reason_val else ""
    feedback_text = f"Employer Feedback: {feedback_val}\n" if feedback_val else ""
    body = (
        f"Dear Student,\n\n"
        f"Thank you for your interest in {company_name}. We regret to inform you that your "
        f"application for '{internship_title}' will not be moving forward at this time.\n\n"
        f"{reason_text}"
        f"{feedback_text}\n"
        f"We encourage you to explore other available internships on SkillMatch."
    )
    send_notification_email(student_email, f"Application Update: {internship_title}", body)


def notify_application_withdrawn(application):
    """
    Notifies employer that the candidate withdrew their application.
    """
    student_email = application.student.email
    company_email = application.internship.company.user.email
    internship_title = application.internship.title
    company_name = application.internship.company.organization_name

    body = (
        f"Dear {company_name},\n\n"
        f"Candidate {student_email} has withdrawn their application for:\n"
        f"- Position: {internship_title}."
    )
    send_notification_email(company_email, f"Application Withdrawn: {internship_title}", body)


def notify_company_student_withdrawn_other_acceptance(application):
    """
    Notifies employer that a pending application was automatically withdrawn
    because the student accepted an offer elsewhere (BUG-08).
    """
    student_email = application.student.email
    company_email = application.internship.company.user.email
    internship_title = application.internship.title
    company_name = application.internship.company.organization_name

    body = (
        f"Dear {company_name},\n\n"
        f"We are writing to inform you that candidate {student_email} has accepted an "
        f"internship offer with another organization, and their pending application for "
        f"'{internship_title}' has been withdrawn.\n\n"
        f"You may continue to review other qualified applicants from your dashboard."
    )
    send_notification_email(company_email, f"Applicant Accepted Another Offer: {internship_title}", body)


def notify_company_student_accepted_elsewhere(application):
    """
    Notifies employer with an outstanding offer that the candidate has accepted an
    offer elsewhere (BUG-08).
    """
    student_email = application.student.email
    company_email = application.internship.company.user.email
    internship_title = application.internship.title
    company_name = application.internship.company.organization_name

    body = (
        f"Dear {company_name},\n\n"
        f"Please be advised that candidate {student_email}, who currently holds an active "
        f"internship offer for '{internship_title}', has accepted an offer with another organization.\n\n"
        f"You may review the status of your offers and applicants from your dashboard."
    )
    send_notification_email(company_email, f"Candidate Accepted Another Offer: {internship_title}", body)


def notify_listing_closed_applicants(pending_applications, internship, reason="positions_filled"):
    """
    Notifies pending applicants when a listing closes because all positions were filled
    or the deadline passed.
    """
    internship_title = internship.title
    company_name = internship.company.organization_name

    reason_msg = (
        "all available positions have now been filled"
        if reason == "positions_filled"
        else "the application deadline has passed"
    )

    for app in pending_applications:
        student_email = app.student.email
        body = (
            f"Dear Student,\n\n"
            f"The internship posting '{internship_title}' at {company_name} has now been closed "
            f"because {reason_msg}.\n\n"
            f"Your pending application has been closed. Please check other open opportunities on SkillMatch."
        )
        send_notification_email(student_email, f"Listing Closed: {internship_title}", body)


def notify_listing_moderation(internship, status):
    """
    Notifies company when their listing is approved or rejected by the admin.
    """
    company_email = internship.company.user.email
    company_name = internship.company.organization_name
    title = internship.title

    if status == "approved":
        body = (
            f"Dear {company_name},\n\n"
            f"Your internship listing '{title}' has been reviewed and APPROVED by the administrator.\n"
            f"It is now publicly visible to eligible students on SkillMatch."
        )
        send_notification_email(company_email, f"Listing Approved: {title}", body)
    else:
        body = (
            f"Dear {company_name},\n\n"
            f"Your internship listing '{title}' has been reviewed and REJECTED by the administrator.\n"
            f"Please review your listing details or contact administration for further clarification."
        )
        send_notification_email(company_email, f"Listing Rejected: {title}", body)


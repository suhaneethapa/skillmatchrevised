from unittest.mock import patch
from datetime import date
from django.test import TestCase, override_settings
from django.core import mail

from accounts.models import User
from core.models import College, Category, Skill
from companies.models import CompanyProfile, Internship
from students.models import StudentProfile, Application
from core.emails import (
    send_notification_email,
    notify_application_submitted,
    notify_offer_issued,
    notify_offer_accepted,
    notify_offer_declined,
    notify_application_rejected,
    notify_application_withdrawn,
    notify_listing_closed_applicants,
    notify_listing_moderation,
)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailNotificationTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Prime College")
        self.category = Category.objects.create(name="Software Engineering")

        self.student_user = User.objects.create_user(
            email="test_student@example.com",
            password="Password123!",
            role="student",
            status="active"
        )
        self.student_profile = StudentProfile.objects.create(
            user=self.student_user,
            college=self.college,
            department="BIM",
            semester=6
        )

        self.company_user = User.objects.create_user(
            email="test_company@example.com",
            password="Password123!",
            role="company",
            status="active"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="Tech Solutions Ltd",
            contact_person="HR Manager",
            industry="IT",
            description="Software development"
        )

        self.internship = Internship.objects.create(
            company=self.company_profile,
            title="Backend Developer Intern",
            description="Django intern position",
            category=self.category,
            location_type="hybrid",
            deadline=date.today(),
            total_positions=2,
            expected_duration="3 months",
            status="approved"
        )

        self.application = Application.objects.create(
            student=self.student_user,
            internship=self.internship,
            match_score=85.00,
            status="pending"
        )

        mail.outbox.clear()

    def test_send_notification_email_plain_text(self):
        with self.captureOnCommitCallbacks(execute=True):
            send_notification_email("recipient@example.com", "Test Subject", "Test message content.")
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("[SkillMatch] Test Subject", email.subject)
        self.assertIn("Test message content.", email.body)
        self.assertIn("SkillMatch Internship Placement System", email.body)
        self.assertEqual(email.to, ["recipient@example.com"])

    def test_notify_application_submitted(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_application_submitted(self.application)
        self.assertEqual(len(mail.outbox), 2)
        recipients = [m.to[0] for m in mail.outbox]
        self.assertIn(self.student_user.email, recipients)
        self.assertIn(self.company_user.email, recipients)

    def test_notify_offer_issued(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_offer_issued(self.application)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.student_user.email])
        self.assertIn("Internship Offer", mail.outbox[0].subject)

    def test_notify_offer_accepted(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_offer_accepted(self.application)
        self.assertEqual(len(mail.outbox), 2)
        recipients = [m.to[0] for m in mail.outbox]
        self.assertIn(self.student_user.email, recipients)
        self.assertIn(self.company_user.email, recipients)

    def test_notify_offer_declined(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_offer_declined(self.application)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.company_user.email])
        self.assertIn("Offer Declined", mail.outbox[0].subject)

    def test_notify_application_rejected_with_feedback(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_application_rejected(self.application, feedback="Need more experience in MySQL.")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.student_user.email])
        self.assertIn("Need more experience in MySQL.", mail.outbox[0].body)

    def test_notify_application_withdrawn(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_application_withdrawn(self.application)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.company_user.email])
        self.assertIn("Application Withdrawn", mail.outbox[0].subject)

    def test_notify_listing_closed_applicants(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_listing_closed_applicants([self.application], self.internship, reason="positions_filled")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.student_user.email])
        self.assertIn("all available positions have now been filled", mail.outbox[0].body)

    def test_notify_listing_moderation_approved_and_rejected(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_listing_moderation(self.internship, "approved")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("APPROVED", mail.outbox[0].body)

        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            notify_listing_moderation(self.internship, "rejected")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("REJECTED", mail.outbox[0].body)

    def test_email_failure_does_not_raise(self):
        """Failure to send email should be logged and not raise an exception (AC-1.4)."""
        with patch("core.emails.send_mail", side_effect=Exception("SMTP Connection Error")):
            with self.captureOnCommitCallbacks(execute=True):
                send_notification_email("error@example.com", "Subject", "Body")

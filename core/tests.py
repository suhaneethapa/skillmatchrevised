import io
import zipfile
from unittest.mock import patch
from datetime import date
from django.test import TestCase, override_settings
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError

from accounts.models import User
from core.models import College, Category, Skill
from companies.models import CompanyProfile, Internship
from students.models import StudentProfile, Application
from core.validators import validate_document_file
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
    notify_email_verification,
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

    def test_notify_email_verification(self):
        verification_url = "http://testserver/accounts/verify/12345678-1234-5678-1234-567812345678/"
        with self.captureOnCommitCallbacks(execute=True):
            notify_email_verification(self.student_user, verification_url)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, [self.student_user.email])
        self.assertIn("Verify Your Email Address", email.subject)
        self.assertIn(verification_url, email.body)
        self.assertIn("valid for 24 hours", email.body)


class DocumentContentValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Create a valid DOCX file in memory
        docx_io = io.BytesIO()
        with zipfile.ZipFile(docx_io, 'w') as zf:
            zf.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>')
            zf.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body></w:body></w:document>')
        cls.valid_docx_bytes = docx_io.getvalue()

        # Create an invalid DOCX (valid zip, but missing word/document.xml)
        bad_docx_io = io.BytesIO()
        with zipfile.ZipFile(bad_docx_io, 'w') as zf:
            zf.writestr('some_file.txt', 'not word')
        cls.missing_components_docx_bytes = bad_docx_io.getvalue()

        # OLE header for .doc
        cls.valid_doc_bytes = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\x00' * 512

    def test_valid_pdf_accepted(self):
        f = SimpleUploadedFile("document.pdf", b"%PDF-1.7 valid pdf stream data", content_type="application/pdf")
        validated = validate_document_file(f)
        self.assertEqual(validated, f)
        self.assertEqual(f.tell(), 0)

    def test_valid_doc_accepted(self):
        f = SimpleUploadedFile("document.doc", self.valid_doc_bytes, content_type="application/msword")
        validated = validate_document_file(f)
        self.assertEqual(validated, f)
        self.assertEqual(f.tell(), 0)

    def test_valid_docx_accepted(self):
        f = SimpleUploadedFile("document.docx", self.valid_docx_bytes, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        validated = validate_document_file(f)
        self.assertEqual(validated, f)
        self.assertEqual(f.tell(), 0)

    def test_disallowed_extension_rejected(self):
        f = SimpleUploadedFile("script.py", b"print('hello')", content_type="text/x-python")
        with self.assertRaises(ValidationError) as ctx:
            validate_document_file(f)
        self.assertIn("Invalid file extension", str(ctx.exception))

    def test_oversized_document_rejected(self):
        oversized = SimpleUploadedFile("huge.pdf", b"%PDF-1.4 " + (b"0" * (5 * 1024 * 1024 + 10)), content_type="application/pdf")
        with self.assertRaises(ValidationError) as ctx:
            validate_document_file(oversized)
        self.assertIn("exceeds the 5 MB limit", str(ctx.exception))

    def test_pdf_with_invalid_header_rejected(self):
        f = SimpleUploadedFile("fake.pdf", b"NOT_A_PDF_HEADER", content_type="application/pdf")
        with self.assertRaises(ValidationError) as ctx:
            validate_document_file(f)
        self.assertIn("Invalid PDF file content", str(ctx.exception))
        self.assertEqual(f.tell(), 0)

    def test_doc_with_invalid_header_rejected(self):
        f = SimpleUploadedFile("fake.doc", b"NOT_OLE_COMPOUND", content_type="application/msword")
        with self.assertRaises(ValidationError) as ctx:
            validate_document_file(f)
        self.assertIn("Invalid Word (.doc) file content", str(ctx.exception))
        self.assertEqual(f.tell(), 0)

    def test_docx_without_zip_header_rejected(self):
        f = SimpleUploadedFile("fake.docx", b"%PDF-1.4 trying to disguise as docx", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with self.assertRaises(ValidationError) as ctx:
            validate_document_file(f)
        self.assertIn("Invalid Word (.docx) file content", str(ctx.exception))
        self.assertEqual(f.tell(), 0)

    def test_docx_missing_required_xml_components_rejected(self):
        f = SimpleUploadedFile("invalid_structure.docx", self.missing_components_docx_bytes, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with self.assertRaises(ValidationError) as ctx:
            validate_document_file(f)
        self.assertIn("Missing required document components", str(ctx.exception))
        self.assertEqual(f.tell(), 0)

    def test_docx_corrupted_zip_archive_rejected(self):
        f = SimpleUploadedFile("corrupted.docx", b"PK\x03\x04\x00\x00truncatedarchivecorrupt", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with self.assertRaises(ValidationError) as ctx:
            validate_document_file(f)
        self.assertIn("Corrupted or malformed archive", str(ctx.exception))
        self.assertEqual(f.tell(), 0)

    def test_docx_with_malformed_xml_rejected(self):
        """ZIP containing both required filenames but malformed XML is rejected."""
        malformed_xml_io = io.BytesIO()
        with zipfile.ZipFile(malformed_xml_io, 'w') as zf:
            zf.writestr('[Content_Types].xml', '<Types><broken>')
            zf.writestr('word/document.xml', '<w:document>Unclosed tag')
        malformed_docx = SimpleUploadedFile(
            "malformed_xml.docx",
            malformed_xml_io.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        with self.assertRaises(ValidationError) as ctx:
            validate_document_file(malformed_docx)
        self.assertIn("Malformed document XML structure", str(ctx.exception))
        self.assertEqual(malformed_docx.tell(), 0)

    def test_docx_oversized_uncompressed_content_types_rejected(self):
        """ZIP entry for [Content_Types].xml exceeding uncompressed size limit is rejected before reading."""
        oversized_ct_io = io.BytesIO()
        with zipfile.ZipFile(oversized_ct_io, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            # 1.1 MB uncompressed, but compresses to ~1 KB
            zf.writestr('[Content_Types].xml', b'<Types>' + (b' ' * (1024 * 1024 + 100)) + b'</Types>')
            zf.writestr('word/document.xml', '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body></w:body></w:document>')
        f = SimpleUploadedFile(
            "oversized_ct.docx",
            oversized_ct_io.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        with self.assertRaises(ValidationError) as ctx:
            validate_document_file(f)
        self.assertIn("Internal package metadata exceeds allowable size limit", str(ctx.exception))
        self.assertEqual(f.tell(), 0)

    def test_docx_oversized_uncompressed_document_xml_rejected(self):
        """ZIP entry for word/document.xml exceeding uncompressed size limit is rejected before reading."""
        oversized_doc_io = io.BytesIO()
        with zipfile.ZipFile(oversized_doc_io, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>')
            # 10.1 MB uncompressed, but compresses to ~10 KB
            zf.writestr('word/document.xml', b'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' + (b' ' * (10 * 1024 * 1024 + 100)) + b'</w:document>')
        f = SimpleUploadedFile(
            "oversized_doc.docx",
            oversized_doc_io.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        with self.assertRaises(ValidationError) as ctx:
            validate_document_file(f)
        self.assertIn("Internal document structure exceeds allowable size limit", str(ctx.exception))
        self.assertEqual(f.tell(), 0)

    def test_file_pointer_restored_on_failure(self):
        f = SimpleUploadedFile("bad.pdf", b"Random bytes that fail validation", content_type="application/pdf")
        with self.assertRaises(ValidationError):
            validate_document_file(f)
        self.assertEqual(f.tell(), 0)

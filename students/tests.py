from datetime import date, timedelta
from unittest.mock import patch
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from core.models import College, Category, Skill
from companies.models import CompanyProfile, Internship, InternshipSkill
from students.models import StudentProfile, StudentSkill, Application


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class Bug02PublicBrowsingRegressionTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Prime College")
        self.category = Category.objects.create(name="Web Frameworks")

        self.python_skill = Skill.objects.create(name="Python", category=self.category)
        self.django_skill = Skill.objects.create(name="Django", category=self.category)

        # Company
        self.company_user = User.objects.create_user(
            email="company_host@demo.local",
            password="DemoPassword123!",
            role="company",
            status="active"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="Tech Valley Pvt. Ltd.",
            contact_person="HR",
            industry="Software",
            description="Software Engineering Studio"
        )

        # Approved Internship
        self.internship = Internship.objects.create(
            company=self.company_profile,
            title="Fullstack Django Intern",
            description="Work on exciting Django web apps.",
            category=self.category,
            location_type="hybrid",
            deadline=date.today(),
            total_positions=2,
            expected_duration="3 months",
            status="approved"
        )
        InternshipSkill.objects.create(internship=self.internship, skill=self.python_skill, is_required=True)
        InternshipSkill.objects.create(internship=self.internship, skill=self.django_skill, is_required=True)

        # Student
        self.student_user = User.objects.create_user(
            email="student_seeker@demo.local",
            password="DemoPassword123!",
            role="student",
            status="active"
        )
        self.student_profile = StudentProfile.objects.create(
            user=self.student_user,
            college=self.college,
            department="BIM",
            semester=6
        )
        StudentSkill.objects.create(student=self.student_user, skill=self.python_skill)
        StudentSkill.objects.create(student=self.student_user, skill=self.django_skill)

    def test_guest_can_browse_internships_without_login(self):
        """Guests must access /student/internships/ without login; non-computable match badges are omitted."""
        response = self.client.get(reverse('students:browse_internships'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fullstack Django Intern")
        self.assertContains(response, "Tech Valley Pvt. Ltd.")
        # Non-computable match pills should not be rendered
        self.assertNotContains(response, "match-pill")

    def test_guest_can_view_listing_detail(self):
        """Guests can view public internship detail page."""
        url = reverse('students:internship_detail', args=[self.internship.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fullstack Django Intern")
        self.assertContains(response, "Work on exciting Django web apps.")
        self.assertContains(response, "Apply Now")

    def test_guest_apply_redirects_to_login_with_message(self):
        """Clicking Apply as a guest redirects to login with message 'Log in or register to apply'."""
        apply_url = reverse('students:apply_internship', args=[self.internship.id])
        response = self.client.get(apply_url, follow=True)
        expected_redirect = f"/login/?next=/student/internships/{self.internship.id}/"
        self.assertRedirects(response, expected_redirect)
        self.assertContains(response, "Log in or register to apply")

    def test_login_resumes_intended_application(self):
        """Logging in returns user to the intended listing detail to resume application."""
        # Guest triggers apply
        apply_url = reverse('students:apply_internship', args=[self.internship.id])
        self.client.get(apply_url)

        # Now login as student
        response = self.client.post(reverse('accounts:login'), {
            'email': self.student_user.email,
            'password': 'DemoPassword123!',
            'next': f'/student/internships/{self.internship.id}/'
        })
        expected_detail_url = reverse('students:internship_detail', args=[self.internship.id])
        self.assertRedirects(response, expected_detail_url)

    def test_registration_flow_does_not_lose_intended_application(self):
        """New student registering via 'next' is automatically guided to intended listing."""
        reg_url = f"{reverse('accounts:register')}?next=/student/internships/{self.internship.id}/"
        response = self.client.post(reg_url, {
            'role': 'student',
            'email': 'new_candidate@demo.local',
            'college': self.college.id,
            'department': 'BIM',
            'semester': 5,
            'password1': 'NewDemoPassword123!',
            'password2': 'NewDemoPassword123!',
            'next': f'/student/internships/{self.internship.id}/'
        })
        expected_detail_url = reverse('students:internship_detail', args=[self.internship.id])
        self.assertRedirects(response, expected_detail_url)

    def test_authenticated_student_sees_match_score(self):
        """Authenticated student sees computed match score on browse and detail."""
        self.client.login(email=self.student_user.email, password="DemoPassword123!")

        # Browse page
        browse_resp = self.client.get(reverse('students:browse_internships'))
        self.assertEqual(browse_resp.status_code, 200)
        self.assertContains(browse_resp, "100.0%")

        # Detail page
        detail_resp = self.client.get(reverse('students:internship_detail', args=[self.internship.id]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, "100.0% Match")


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class Bug03RevalidateSkillsRegressionTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Prime College")
        self.category = Category.objects.create(name="Web Frameworks")

        self.python_skill = Skill.objects.create(name="Python", category=self.category)
        self.django_skill = Skill.objects.create(name="Django", category=self.category)

        # Company
        self.company_user = User.objects.create_user(
            email="company_evaluator@demo.local",
            password="DemoPassword123!",
            role="company",
            status="active"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="Tech Valley Pvt. Ltd.",
            contact_person="HR Director",
            industry="IT",
            description="Software Engineering Studio"
        )

        # Approved Internship
        self.internship = Internship.objects.create(
            company=self.company_profile,
            title="Backend Engineer Intern",
            description="Python & Django internship",
            category=self.category,
            location_type="remote",
            deadline=date.today(),
            total_positions=2,
            expected_duration="3 months",
            status="approved"
        )
        InternshipSkill.objects.create(internship=self.internship, skill=self.python_skill, is_required=True)
        InternshipSkill.objects.create(internship=self.internship, skill=self.django_skill, is_required=True)

        # Student with skills
        self.student_user = User.objects.create_user(
            email="candidate_reval@demo.local",
            password="DemoPassword123!",
            role="student",
            status="active"
        )
        self.student_profile = StudentProfile.objects.create(
            user=self.student_user,
            college=self.college,
            department="BIM",
            semester=6
        )
        StudentSkill.objects.create(student=self.student_user, skill=self.python_skill)
        StudentSkill.objects.create(student=self.student_user, skill=self.django_skill)

        # Application submitted with 100% score
        self.application = Application.objects.create(
            student=self.student_user,
            internship=self.internship,
            match_score=100.0,
            status='pending'
        )

    def test_skills_drop_below_threshold_recomputes_live_on_student_dashboard(self):
        """When student edits skills to drop below 50%, student dashboard recomputes score and displays warning."""
        # Student removes all skills
        StudentSkill.objects.filter(student=self.student_user).delete()

        self.client.login(email=self.student_user.email, password="DemoPassword123!")
        response = self.client.get(reverse('students:dashboard'))
        self.assertEqual(response.status_code, 200)

        # Stored application match_score should be updated to 0.00%
        self.application.refresh_from_db()
        self.assertEqual(float(self.application.match_score), 0.0)
        self.assertTrue(self.application.is_below_threshold)

        # Warning chip must be visible on the dashboard
        self.assertContains(response, "Below threshold &mdash; skills updated")

    def test_skills_drop_below_threshold_displays_warning_on_company_applicant_list(self):
        """When student skills drop below 50%, company applicant list recomputes and displays warning chip."""
        # Student removes all skills
        StudentSkill.objects.filter(student=self.student_user).delete()

        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        url = reverse('companies:view_applicants', args=[self.internship.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Recomputed live score and warning displayed
        self.assertContains(response, "0.0%")
        self.assertContains(response, "Below threshold &mdash; skills updated")

    def test_skills_drop_below_threshold_displays_warning_on_browse_and_detail(self):
        """Browse internships and detail page must flag already applied listing if student drops below threshold."""
        # Student removes skills
        StudentSkill.objects.filter(student=self.student_user).delete()

        self.client.login(email=self.student_user.email, password="DemoPassword123!")

        # Browse page
        browse_resp = self.client.get(reverse('students:browse_internships'))
        self.assertEqual(browse_resp.status_code, 200)
        self.assertContains(browse_resp, "Below threshold &mdash; skills updated")

        # Detail page
        detail_resp = self.client.get(reverse('students:internship_detail', args=[self.internship.id]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, "Below threshold &mdash; skills updated")


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class Bug04PreventDuplicateApplicationsRegressionTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Prime College")
        self.category = Category.objects.create(name="Web Dev")
        self.python_skill = Skill.objects.create(name="Python", category=self.category)

        # Company
        self.company_user = User.objects.create_user(
            email="company_dup@demo.local",
            password="DemoPassword123!",
            role="company",
            status="active"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="Dup Corp",
            contact_person="Recruiter",
            industry="IT",
            description="Testing duplicate handling"
        )

        # Approved Internship
        self.internship = Internship.objects.create(
            company=self.company_profile,
            title="Python Developer Intern",
            description="Internship for duplicate testing",
            category=self.category,
            location_type="remote",
            deadline=date.today(),
            total_positions=2,
            expected_duration="3 months",
            status="approved"
        )
        InternshipSkill.objects.create(internship=self.internship, skill=self.python_skill, is_required=True)

        # Student with CV and required skill
        self.student_user = User.objects.create_user(
            email="student_dup@demo.local",
            password="DemoPassword123!",
            role="student",
            status="active"
        )
        dummy_cv = SimpleUploadedFile("cv.pdf", b"%PDF-1.4 dummy content", content_type="application/pdf")
        self.student_profile = StudentProfile.objects.create(
            user=self.student_user,
            college=self.college,
            department="BIM",
            semester=6,
            cv_file=dummy_cv
        )
        StudentSkill.objects.create(student=self.student_user, skill=self.python_skill)

    def test_database_unique_constraint_enforces_single_application(self):
        """Database unique constraint on (student, internship) must prevent duplicate rows."""
        Application.objects.create(
            student=self.student_user,
            internship=self.internship,
            match_score=100.0,
            status='pending'
        )
        with self.assertRaises(IntegrityError):
            Application.objects.create(
                student=self.student_user,
                internship=self.internship,
                match_score=100.0,
                status='pending'
            )

    def test_idempotent_apply_view_on_double_submit(self):
        """Submitting application twice via POST must be idempotent and redirect gracefully without 500 error."""
        self.client.login(email=self.student_user.email, password="DemoPassword123!")
        apply_url = reverse('students:apply_internship', args=[self.internship.id])

        # First submit
        resp1 = self.client.post(apply_url, {'cover_letter': 'First submission'}, follow=True)
        self.assertRedirects(resp1, reverse('students:dashboard'))
        self.assertEqual(Application.objects.filter(student=self.student_user, internship=self.internship).count(), 1)
        self.assertContains(resp1, "Application submitted!")

        # Second submit (simulating refresh / double-click)
        resp2 = self.client.post(apply_url, {'cover_letter': 'Duplicate attempt'}, follow=True)
        self.assertEqual(resp2.status_code, 200)
        self.assertRedirects(resp2, reverse('students:internship_detail', args=[self.internship.id]))
        self.assertEqual(Application.objects.filter(student=self.student_user, internship=self.internship).count(), 1)
        self.assertContains(resp2, "You have already applied to this internship.")

    def test_apply_view_handles_concurrent_race_integrity_error(self):
        """If IntegrityError occurs during concurrent creation, apply view catches it and warns gracefully."""
        self.client.login(email=self.student_user.email, password="DemoPassword123!")
        apply_url = reverse('students:apply_internship', args=[self.internship.id])

        with patch.object(Application, 'save') as mock_save:
            mock_save.side_effect = IntegrityError("Duplicate entry")
            response = self.client.post(apply_url, {'cover_letter': 'Concurrent submit'}, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertRedirects(response, reverse('students:internship_detail', args=[self.internship.id]))
            self.assertContains(response, "You have already applied to this internship.")

    def test_get_request_does_not_create_application(self):
        """Authenticated student accessing apply via GET is redirected without creating an application."""
        self.client.login(email=self.student_user.email, password="DemoPassword123!")
        apply_url = reverse('students:apply_internship', args=[self.internship.id])

        response = self.client.get(apply_url)
        self.assertRedirects(response, reverse('students:internship_detail', args=[self.internship.id]))
        self.assertEqual(Application.objects.filter(student=self.student_user, internship=self.internship).count(), 0)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class Bug05EnforceListingStatusAndDeadlineRegressionTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Prime College")
        self.category = Category.objects.create(name="Web Dev")
        self.python_skill = Skill.objects.create(name="Python", category=self.category)

        # Company
        self.company_user = User.objects.create_user(
            email="company_b05@demo.local",
            password="DemoPassword123!",
            role="company",
            status="active"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="Deadline Corp",
            contact_person="HR",
            industry="IT",
            description="Testing deadline and status enforcement"
        )

        # Internship
        self.internship = Internship.objects.create(
            company=self.company_profile,
            title="Backend Python Intern",
            description="Internship for deadline testing",
            category=self.category,
            location_type="remote",
            deadline=date.today(),
            total_positions=2,
            expected_duration="3 months",
            status="approved"
        )
        InternshipSkill.objects.create(internship=self.internship, skill=self.python_skill, is_required=True)

        # Student with CV and required skill
        self.student_user = User.objects.create_user(
            email="student_b05@demo.local",
            password="DemoPassword123!",
            role="student",
            status="active"
        )
        dummy_cv = SimpleUploadedFile("cv.pdf", b"%PDF-1.4 dummy content", content_type="application/pdf")
        self.student_profile = StudentProfile.objects.create(
            user=self.student_user,
            college=self.college,
            department="BIM",
            semester=6,
            cv_file=dummy_cv
        )
        StudentSkill.objects.create(student=self.student_user, skill=self.python_skill)

    def test_cannot_apply_to_expired_listing(self):
        """Applying to an internship whose deadline has passed must be rejected inside the apply transaction."""
        self.internship.deadline = date.today() - timedelta(days=1)
        self.internship.save()

        self.client.login(email=self.student_user.email, password="DemoPassword123!")
        apply_url = reverse('students:apply_internship', args=[self.internship.id])

        response = self.client.post(apply_url, {'cover_letter': 'Applying late'}, follow=True)
        self.assertRedirects(response, reverse('students:internship_detail', args=[self.internship.id]))
        self.assertContains(response, "This internship listing has closed because the application deadline has passed.")
        self.assertEqual(Application.objects.filter(student=self.student_user, internship=self.internship).count(), 0)

    def test_cannot_apply_to_closed_listing(self):
        """Applying to a closed internship listing must be rejected inside the apply transaction."""
        self.internship.status = 'closed'
        self.internship.save()

        self.client.login(email=self.student_user.email, password="DemoPassword123!")
        apply_url = reverse('students:apply_internship', args=[self.internship.id])

        response = self.client.post(apply_url, {'cover_letter': 'Applying to closed'}, follow=True)
        self.assertRedirects(response, reverse('students:browse_internships'))
        self.assertContains(response, "This internship listing is closed and no longer accepting applications.")
        self.assertEqual(Application.objects.filter(student=self.student_user, internship=self.internship).count(), 0)

    def test_model_clean_blocks_expired_or_non_approved_application(self):
        """Model-level clean() blocks creating applications for expired or unapproved listings."""
        self.internship.deadline = date.today() - timedelta(days=2)
        self.internship.save()

        app = Application(
            student=self.student_user,
            internship=self.internship,
            match_score=100.0,
            status='pending'
        )
        with self.assertRaises(ValidationError):
            app.full_clean()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class Bug08AutoWithdrawOtherApplicationsRegressionTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Prime College")
        self.category = Category.objects.create(name="Tech")
        self.python_skill = Skill.objects.create(name="Python", category=self.category)

        # Student
        self.student = User.objects.create_user(
            email="candidate_b08@demo.local",
            password="DemoPassword123!",
            role="student",
            status="active"
        )
        self.profile = StudentProfile.objects.create(
            user=self.student,
            college=self.college,
            department="BIM",
            semester=6
        )
        StudentSkill.objects.create(student=self.student, skill=self.python_skill)

        # Company A (Listing A)
        self.comp_user_a = User.objects.create_user(email="comp_a@demo.local", password="DemoPassword123!", role="company", status="active")
        self.comp_prof_a = CompanyProfile.objects.create(user=self.comp_user_a, organization_name="Company Alpha", contact_person="HR A", industry="IT")
        self.internship_a = Internship.objects.create(
            company=self.comp_prof_a, title="Alpha Role", category=self.category,
            location_type="remote", deadline=date.today() + timedelta(days=10), total_positions=2, expected_duration="3 months", status="approved"
        )
        InternshipSkill.objects.create(internship=self.internship_a, skill=self.python_skill, is_required=True)

        # Company B (Listing B - The Offer Accepted)
        self.comp_user_b = User.objects.create_user(email="comp_b@demo.local", password="DemoPassword123!", role="company", status="active")
        self.comp_prof_b = CompanyProfile.objects.create(user=self.comp_user_b, organization_name="Company Beta", contact_person="HR B", industry="IT")
        self.internship_b = Internship.objects.create(
            company=self.comp_prof_b, title="Beta Role", category=self.category,
            location_type="remote", deadline=date.today() + timedelta(days=10), total_positions=2, expected_duration="3 months", status="approved"
        )
        InternshipSkill.objects.create(internship=self.internship_b, skill=self.python_skill, is_required=True)

        # Company C (Listing C - Holds Another Offer)
        self.comp_user_c = User.objects.create_user(email="comp_c@demo.local", password="DemoPassword123!", role="company", status="active")
        self.comp_prof_c = CompanyProfile.objects.create(user=self.comp_user_c, organization_name="Company Gamma", contact_person="HR C", industry="IT")
        self.internship_c = Internship.objects.create(
            company=self.comp_prof_c, title="Gamma Role", category=self.category,
            location_type="remote", deadline=date.today() + timedelta(days=10), total_positions=2, expected_duration="3 months", status="approved"
        )
        InternshipSkill.objects.create(internship=self.internship_c, skill=self.python_skill, is_required=True)

        # Applications:
        # App A is pending
        self.app_a = Application.objects.create(student=self.student, internship=self.internship_a, match_score=100.0, status='pending')
        # App B is offer_issued (to be accepted)
        self.app_b = Application.objects.create(student=self.student, internship=self.internship_b, match_score=100.0, status='offer_issued')
        # App C is offer_issued (holds competing offer)
        self.app_c = Application.objects.create(student=self.student, internship=self.internship_c, match_score=100.0, status='offer_issued')

        mail.outbox.clear()

    def test_accept_offer_auto_withdraws_pending_applications_and_notifies(self):
        """Accepting an offer auto-withdraws pending applications and sends neutral notice to company."""
        self.client.login(email=self.student.email, password="DemoPassword123!")
        accept_url = reverse('students:accept_offer', args=[self.app_b.id])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(accept_url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Congratulations! You have accepted the offer")

        # App B accepted
        self.app_b.refresh_from_db()
        self.assertEqual(self.app_b.status, 'accepted')

        # App A (pending) must be auto-withdrawn
        self.app_a.refresh_from_db()
        self.assertEqual(self.app_a.status, 'withdrawn')

        # Company A received neutral notice
        comp_a_emails = [e for e in mail.outbox if "comp_a@demo.local" in e.to]
        self.assertTrue(len(comp_a_emails) >= 1)
        self.assertIn("has accepted an internship offer with another organization", comp_a_emails[0].body)
        self.assertIn("pending application for 'Alpha Role' has been withdrawn", comp_a_emails[0].body)

    def test_accept_offer_does_not_auto_withdraw_other_offers_but_sends_notice(self):
        """Applications that already received offers are NOT auto-withdrawn; company receives notice instead."""
        self.client.login(email=self.student.email, password="DemoPassword123!")
        accept_url = reverse('students:accept_offer', args=[self.app_b.id])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(accept_url, follow=True)

        self.assertEqual(response.status_code, 200)

        # App C (competing offer) remains offer_issued
        self.app_c.refresh_from_db()
        self.assertEqual(self.app_c.status, 'offer_issued')

        # Company C received notice that student accepted elsewhere
        comp_c_emails = [e for e in mail.outbox if "comp_c@demo.local" in e.to]
        self.assertTrue(len(comp_c_emails) >= 1)
        self.assertIn("who currently holds an active internship offer for 'Gamma Role', has accepted an offer with another organization", comp_c_emails[0].body)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class Bug09SessionAndApprovalGatesRegressionTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Prime College")
        self.category = Category.objects.create(name="Tech")
        self.python_skill = Skill.objects.create(name="Python", category=self.category)

        # Company
        self.company_user = User.objects.create_user(
            email="company_b09@demo.local",
            password="DemoPassword123!",
            role="company",
            status="active"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="Gate Corp",
            contact_person="HR",
            industry="IT"
        )
        self.internship = Internship.objects.create(
            company=self.company_profile,
            title="Gate Intern",
            category=self.category,
            location_type="remote",
            deadline=date.today() + timedelta(days=10),
            total_positions=2,
            expected_duration="3 months",
            status="approved"
        )
        InternshipSkill.objects.create(internship=self.internship, skill=self.python_skill, is_required=True)

        # Student with pending_admin status
        self.student = User.objects.create_user(
            email="pending_student@demo.local",
            password="DemoPassword123!",
            role="student",
            status="pending_admin"
        )
        dummy_cv = SimpleUploadedFile("cv.pdf", b"%PDF-1.4 dummy content", content_type="application/pdf")
        self.profile = StudentProfile.objects.create(
            user=self.student,
            college=self.college,
            department="BIM",
            semester=6,
            cv_file=dummy_cv
        )
        StudentSkill.objects.create(student=self.student, skill=self.python_skill)

    def test_unapproved_student_cannot_apply_and_sees_awaiting_approval_message(self):
        """Student whose account is awaiting admin approval cannot apply and sees clear explanation."""
        self.client.login(email=self.student.email, password="DemoPassword123!")

        # Detail page renders awaiting approval banner instead of apply form
        detail_resp = self.client.get(reverse('students:internship_detail', args=[self.internship.id]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, "Your account is awaiting approval from the administrator")

        # Direct POST apply attempt is blocked with exact required message
        apply_url = reverse('students:apply_internship', args=[self.internship.id])
        post_resp = self.client.post(apply_url, {'cover_letter': 'Trying to apply'}, follow=True)
        self.assertEqual(post_resp.status_code, 200)
        self.assertContains(post_resp, "Your account is awaiting approval")
        self.assertEqual(Application.objects.filter(student=self.student, internship=self.internship).count(), 0)

    def test_suspended_user_immediately_logged_out_by_middleware(self):
        """When an account is suspended, middleware immediately terminates the session."""
        self.student.status = 'active'
        self.student.save()
        self.client.login(email=self.student.email, password="DemoPassword123!")

        # Access dashboard as active student
        resp_active = self.client.get(reverse('students:dashboard'))
        self.assertEqual(resp_active.status_code, 200)

        # Account is suspended
        self.student.status = 'suspended'
        self.student.save()

        # Subsequent request must immediately logout and redirect to login
        resp_suspended = self.client.get(reverse('students:dashboard'), follow=True)
        self.assertRedirects(resp_suspended, reverse('accounts:login'))
        self.assertContains(resp_suspended, "Your account has been suspended by the administrator")

    def test_suspended_company_immediately_logged_out_by_middleware(self):
        """When a company profile is suspended, middleware immediately terminates their session."""
        self.client.login(email=self.company_user.email, password="DemoPassword123!")

        # Access dashboard as active company
        resp_active = self.client.get(reverse('companies:dashboard'))
        self.assertEqual(resp_active.status_code, 200)

        # Company profile is suspended
        self.company_profile.suspended = True
        self.company_profile.save()

        # Subsequent request must immediately logout and redirect to login
        resp_suspended = self.client.get(reverse('companies:dashboard'), follow=True)
        self.assertRedirects(resp_suspended, reverse('accounts:login'))
        self.assertContains(resp_suspended, "Your company account has been suspended by the administrator")


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class Bug10FileUploadValidationRegressionTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Prime College")
        self.category = Category.objects.create(name="Tech")
        self.python_skill = Skill.objects.create(name="Python", category=self.category)

        # Student
        self.student = User.objects.create_user(
            email="candidate_upload@demo.local",
            password="DemoPassword123!",
            role="student",
            status="active"
        )
        self.profile = StudentProfile.objects.create(
            user=self.student,
            college=self.college,
            department="BIM",
            semester=6
        )

        # Company
        self.company_user = User.objects.create_user(
            email="company_upload@demo.local",
            password="DemoPassword123!",
            role="company",
            status="active"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="Upload Corp",
            contact_person="HR",
            industry="IT"
        )
        self.internship = Internship.objects.create(
            company=self.company_profile,
            title="Upload Intern",
            category=self.category,
            location_type="remote",
            deadline=date.today() + timedelta(days=10),
            total_positions=2,
            expected_duration="3 months",
            status="approved"
        )
        self.app = Application.objects.create(
            student=self.student,
            internship=self.internship,
            match_score=100.0,
            status='pending'
        )

    def test_cv_upload_rejects_disallowed_extension(self):
        """Uploading a file with disallowed extension (.exe, .png) is rejected at form and view layers."""
        self.client.login(email=self.student.email, password="DemoPassword123!")
        url = reverse('students:profile_edit')

        fake_exe = SimpleUploadedFile("malicious.exe", b"binary executable content", content_type="application/octet-stream")
        response = self.client.post(url, {
            'department': 'BIM',
            'semester': 6,
            'college': self.college.id,
            'cv_file': fake_exe
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid file extension")

        self.profile.refresh_from_db()
        self.assertFalse(bool(self.profile.cv_file))

    def test_cv_upload_rejects_oversized_file(self):
        """Uploading a file exceeding 5 MB is rejected at form and view layers."""
        self.client.login(email=self.student.email, password="DemoPassword123!")
        url = reverse('students:profile_edit')

        # 5.5 MB file
        big_content = b"0" * (int(5.5 * 1024 * 1024))
        big_pdf = SimpleUploadedFile("large_cv.pdf", big_content, content_type="application/pdf")

        response = self.client.post(url, {
            'department': 'BIM',
            'semester': 6,
            'college': self.college.id,
            'cv_file': big_pdf
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "File size exceeds the 5 MB limit")

        self.profile.refresh_from_db()
        self.assertFalse(bool(self.profile.cv_file))

    def test_cv_upload_accepts_valid_pdf_doc_docx(self):
        """Uploading valid PDF, DOC, and DOCX files under 5 MB succeeds."""
        self.client.login(email=self.student.email, password="DemoPassword123!")
        url = reverse('students:profile_edit')

        valid_pdf = SimpleUploadedFile("resume.pdf", b"%PDF-1.4 valid content", content_type="application/pdf")
        response = self.client.post(url, {
            'department': 'BIM',
            'semester': 6,
            'college': self.college.id,
            'cv_file': valid_pdf
        })
        self.assertRedirects(response, reverse('students:profile'))

        self.profile.refresh_from_db()
        self.assertTrue(bool(self.profile.cv_file))
        self.assertTrue(self.profile.cv_file.name.endswith('.pdf'))

    def test_offer_letter_upload_validation(self):
        """Offer letter upload rejects invalid file extensions and accepts valid document files."""
        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        url = reverse('companies:issue_offer', args=[self.app.id])

        # Test invalid extension
        invalid_file = SimpleUploadedFile("offer.txt", b"plain text letter", content_type="text/plain")
        resp_invalid = self.client.post(url, {'offer_letter': invalid_file})
        self.assertEqual(resp_invalid.status_code, 200)
        self.assertContains(resp_invalid, "Invalid file extension")
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'pending')

        # Test valid pdf
        valid_offer = SimpleUploadedFile("official_offer.pdf", b"%PDF-1.4 official offer", content_type="application/pdf")
        resp_valid = self.client.post(url, {'offer_letter': valid_offer})
        self.assertRedirects(resp_valid, reverse('companies:view_applicants', args=[self.internship.id]))
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'offer_issued')
        self.assertTrue(bool(self.app.offer_letter))


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class WithdrawApplicationSecurityRegressionTests(TestCase):
    def setUp(self):
        mail.outbox.clear()
        self.college = College.objects.create(name="Security College")
        self.category = Category.objects.create(name="Engineering")

        self.student = User.objects.create_user(
            email="sec_student@example.com",
            password="DemoPassword123!",
            role="student",
            status="active"
        )
        self.profile = StudentProfile.objects.create(
            user=self.student,
            college=self.college,
            department="BIM",
            semester=6,
            college_verified=True
        )

        self.other_student = User.objects.create_user(
            email="other_sec_student@example.com",
            password="DemoPassword123!",
            role="student",
            status="active"
        )
        self.other_profile = StudentProfile.objects.create(
            user=self.other_student,
            college=self.college,
            department="BIM",
            semester=6,
            college_verified=True
        )

        self.company_user = User.objects.create_user(
            email="sec_company@example.com",
            password="DemoPassword123!",
            role="company",
            status="active"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="Secured Org",
            contact_person="Admin",
            industry="IT"
        )
        self.internship = Internship.objects.create(
            company=self.company_profile,
            title="Secured Role",
            category=self.category,
            location_type="remote",
            deadline=date.today() + timedelta(days=10),
            total_positions=2,
            expected_duration="3 months",
            status="approved"
        )
        self.app = Application.objects.create(
            student=self.student,
            internship=self.internship,
            match_score=80.0,
            status='pending'
        )

    def test_withdraw_rejects_get_and_requires_post(self):
        """GET request to withdraw endpoint is rejected with 405 Method Not Allowed; status is unchanged."""
        self.client.login(email=self.student.email, password="DemoPassword123!")
        withdraw_url = reverse('students:withdraw_application', args=[self.app.id])

        response = self.client.get(withdraw_url)
        self.assertEqual(response.status_code, 405)

        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'pending')

    def test_withdraw_post_succeeds_and_updates_status(self):
        """POST request withdraws application and sends withdrawal notice to company."""
        self.client.login(email=self.student.email, password="DemoPassword123!")
        withdraw_url = reverse('students:withdraw_application', args=[self.app.id])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(withdraw_url)
        self.assertRedirects(response, reverse('students:dashboard'))

        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'withdrawn')

        # Verify notification email sent to company
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Secured Org", mail.outbox[0].body)
        self.assertIn("has withdrawn their application", mail.outbox[0].body)

    def test_withdraw_cannot_withdraw_non_pending_application(self):
        """Attempting to withdraw an application that is not in pending state returns 404."""
        self.client.login(email=self.student.email, password="DemoPassword123!")
        self.app.status = 'accepted'
        self.app.save()

        withdraw_url = reverse('students:withdraw_application', args=[self.app.id])
        response = self.client.post(withdraw_url)
        self.assertEqual(response.status_code, 404)

        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'accepted')

    def test_other_student_cannot_withdraw_foreign_application(self):
        """Another student cannot withdraw an application belonging to someone else."""
        self.client.login(email=self.other_student.email, password="DemoPassword123!")
        withdraw_url = reverse('students:withdraw_application', args=[self.app.id])

        response = self.client.post(withdraw_url)
        self.assertEqual(response.status_code, 404)

        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'pending')

    def test_dashboard_and_applications_pages_render_post_form_with_csrf_and_confirm(self):
        """Dashboard renders POST form with CSRF and confirmation prompt for pending applications."""
        self.client.login(email=self.student.email, password="DemoPassword123!")

        # Dashboard
        dash_resp = self.client.get(reverse('students:dashboard'))
        self.assertEqual(dash_resp.status_code, 200)
        self.assertContains(dash_resp, f'action="{reverse("students:withdraw_application", args=[self.app.id])}"')
        self.assertContains(dash_resp, 'method="post"')
        self.assertContains(dash_resp, "Withdraw this application?")

        # My applications route redirects to dashboard and renders the same form
        apps_resp = self.client.get(reverse('students:my_applications'), follow=True)
        self.assertEqual(apps_resp.status_code, 200)
        self.assertContains(apps_resp, f'action="{reverse("students:withdraw_application", args=[self.app.id])}"')
        self.assertContains(apps_resp, 'method="post"')
        self.assertContains(apps_resp, "Withdraw this application?")








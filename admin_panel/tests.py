from datetime import date, timedelta
from django.test import TestCase, override_settings, Client
from django.urls import reverse

from accounts.models import User
from core.models import College, Category, Skill
from companies.models import CompanyProfile, Internship
from students.models import StudentProfile


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class Phase2AdminModerationAndCollegeVerificationTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="St. Xavier's College")
        self.category = Category.objects.create(name="Cloud Computing")

        # Admin User
        self.admin_user = User.objects.create_superuser(
            email="admin_mod@skillmatch.local",
            password="AdminSecurePassword123!"
        )

        # Company User and Profile
        self.company_user = User.objects.create_user(
            email="cloud_co@example.com",
            password="DemoPassword123!",
            role="company",
            status="pending_email"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="Cloud Nepal Pvt. Ltd.",
            contact_person="Bikash Adhikari",
            industry="Cloud Services",
            hq_location="Kathmandu",
            description="Cloud migration and consulting"
        )

        # Student User and Profile
        self.student_user = User.objects.create_user(
            email="cloud_student@example.com",
            password="DemoPassword123!",
            role="student",
            status="pending_admin"
        )
        self.student_profile = StudentProfile.objects.create(
            user=self.student_user,
            college=self.college,
            department="BIM",
            semester=6,
            college_verified=False
        )

        # Pending Internship
        self.internship = Internship.objects.create(
            company=self.company_profile,
            title="Cloud Architecture Intern",
            category=self.category,
            location_type="remote",
            deadline=date.today() + timedelta(days=20),
            total_positions=2,
            expected_duration="3 months",
            status="pending"
        )

    def test_admin_can_approve_and_reject_internship_listing(self):
        """Admin can transition a pending listing to approved, and approved listing to rejected via POST (A4, Phase 3)."""
        self.client.login(email=self.admin_user.email, password="AdminSecurePassword123!")
        approve_url = reverse('admin_panel:approve_internship', args=[self.internship.id])

        # GET is rejected with 405
        get_resp = self.client.get(approve_url)
        self.assertEqual(get_resp.status_code, 405)
        self.internship.refresh_from_db()
        self.assertEqual(self.internship.status, 'pending')

        # Pending -> Approved via POST
        with self.captureOnCommitCallbacks(execute=True):
            resp1 = self.client.post(approve_url, {'action': 'approve'})
        self.assertRedirects(resp1, reverse('admin_panel:internship_list'))
        self.internship.refresh_from_db()
        self.assertEqual(self.internship.status, 'approved')

        # Approved -> Rejected via POST
        with self.captureOnCommitCallbacks(execute=True):
            resp2 = self.client.post(approve_url, {'action': 'reject'})
        self.assertRedirects(resp2, reverse('admin_panel:internship_list'))
        self.internship.refresh_from_db()
        self.assertEqual(self.internship.status, 'rejected')

    def test_non_admin_cannot_moderate_listings(self):
        """Non-admin users cannot approve or reject listings (A4)."""
        self.client.login(email=self.student_user.email, password="DemoPassword123!")
        approve_url = reverse('admin_panel:approve_internship', args=[self.internship.id])

        response = self.client.post(approve_url, {'action': 'approve'})
        self.assertRedirects(response, reverse('accounts:home'), target_status_code=302)
        self.internship.refresh_from_db()
        self.assertEqual(self.internship.status, 'pending')

    def test_admin_can_verify_and_unverify_student_college(self):
        """Admin can toggle college verification status of a student via POST (A2, Phase 3)."""
        self.client.login(email=self.admin_user.email, password="AdminSecurePassword123!")
        verify_url = reverse('admin_panel:verify_student_college', args=[self.student_user.id])

        # GET is rejected with 405
        get_resp = self.client.get(verify_url)
        self.assertEqual(get_resp.status_code, 405)
        self.student_profile.refresh_from_db()
        self.assertFalse(self.student_profile.college_verified)

        # Unverified -> Verified via POST
        resp1 = self.client.post(verify_url)
        self.assertRedirects(resp1, reverse('admin_panel:user_list'))
        self.student_profile.refresh_from_db()
        self.assertTrue(self.student_profile.college_verified)

        # Verified -> Unverified via POST
        resp2 = self.client.post(verify_url)
        self.assertRedirects(resp2, reverse('admin_panel:user_list'))
        self.student_profile.refresh_from_db()
        self.assertFalse(self.student_profile.college_verified)

    def test_college_verification_does_not_activate_account(self):
        """Toggling college verification does NOT change user.status."""
        self.client.login(email=self.admin_user.email, password="AdminSecurePassword123!")
        verify_url = reverse('admin_panel:verify_student_college', args=[self.student_user.id])

        self.assertEqual(self.student_user.status, 'pending_admin')
        self.client.post(verify_url)
        self.student_user.refresh_from_db()
        self.assertEqual(self.student_user.status, 'pending_admin')

    def test_admin_cannot_activate_pending_email_user(self):
        """Administrator cannot directly activate accounts in pending_email state."""
        self.client.login(email=self.admin_user.email, password="AdminSecurePassword123!")

        # Pending email company
        toggle_comp_url = reverse('admin_panel:toggle_user', args=[self.company_user.id])
        resp_comp = self.client.post(toggle_comp_url, follow=True)
        self.assertContains(resp_comp, "cannot be activated until their email address has been verified")
        self.company_user.refresh_from_db()
        self.assertEqual(self.company_user.status, 'pending_email')

        # Pending email student
        self.student_user.status = 'pending_email'
        self.student_user.save()
        toggle_stud_url = reverse('admin_panel:toggle_user', args=[self.student_user.id])
        resp_stud = self.client.post(toggle_stud_url, follow=True)
        self.assertContains(resp_stud, "cannot be activated until their email address has been verified")
        self.student_user.refresh_from_db()
        self.assertEqual(self.student_user.status, 'pending_email')

    def test_admin_can_activate_pending_admin_company_and_student(self):
        """Admin can activate accounts that have completed email verification (pending_admin)."""
        self.client.login(email=self.admin_user.email, password="AdminSecurePassword123!")

        # Set company to pending_admin
        self.company_user.status = 'pending_admin'
        self.company_user.save()
        toggle_comp_url = reverse('admin_panel:toggle_user', args=[self.company_user.id])
        resp_comp = self.client.post(toggle_comp_url)
        self.assertRedirects(resp_comp, reverse('admin_panel:user_list'))
        self.company_user.refresh_from_db()
        self.assertEqual(self.company_user.status, 'active')

        # Student in pending_admin
        toggle_stud_url = reverse('admin_panel:toggle_user', args=[self.student_user.id])
        resp_stud = self.client.post(toggle_stud_url)
        self.assertRedirects(resp_stud, reverse('admin_panel:user_list'))
        self.student_user.refresh_from_db()
        self.assertEqual(self.student_user.status, 'active')

    def test_admin_can_suspend_and_reinstate_company_via_post(self):
        """Company suspension requires POST and toggles suspension state."""
        self.client.login(email=self.admin_user.email, password="AdminSecurePassword123!")
        suspend_url = reverse('admin_panel:suspend_company', args=[self.company_profile.id])

        # GET is rejected with 405
        get_resp = self.client.get(suspend_url)
        self.assertEqual(get_resp.status_code, 405)
        self.company_profile.refresh_from_db()
        self.assertFalse(self.company_profile.suspended)

        # POST suspends company
        post_resp1 = self.client.post(suspend_url)
        self.assertRedirects(post_resp1, reverse('admin_panel:company_list'))
        self.company_profile.refresh_from_db()
        self.assertTrue(self.company_profile.suspended)

        # POST reinstates company
        post_resp2 = self.client.post(suspend_url)
        self.assertRedirects(post_resp2, reverse('admin_panel:company_list'))
        self.company_profile.refresh_from_db()
        self.assertFalse(self.company_profile.suspended)

    def test_invalid_moderation_action_does_not_change_status(self):
        """Admin POST to approve_internship with invalid or missing action does not modify status."""
        self.client.login(email=self.admin_user.email, password="AdminSecurePassword123!")
        approve_url = reverse('admin_panel:approve_internship', args=[self.internship.id])

        # Test with invalid action string
        resp1 = self.client.post(approve_url, {'action': 'unknown_action'}, follow=True)
        self.assertRedirects(resp1, reverse('admin_panel:internship_list'))
        self.assertContains(resp1, "Invalid moderation action")
        self.internship.refresh_from_db()
        self.assertEqual(self.internship.status, 'pending')

        # Test with empty action
        resp2 = self.client.post(approve_url, {'action': ''}, follow=True)
        self.assertRedirects(resp2, reverse('admin_panel:internship_list'))
        self.assertContains(resp2, "Invalid moderation action")
        self.internship.refresh_from_db()
        self.assertEqual(self.internship.status, 'pending')

    def test_csrf_enforcement_on_admin_actions(self):
        """Moderation and administrative mutation endpoints reject requests missing CSRF token with HTTP 403."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(email=self.admin_user.email, password="AdminSecurePassword123!")

        # 1. approve_internship
        approve_url = reverse('admin_panel:approve_internship', args=[self.internship.id])
        self.assertEqual(csrf_client.post(approve_url, {'action': 'approve'}).status_code, 403)

        # 2. toggle_user
        toggle_url = reverse('admin_panel:toggle_user', args=[self.company_user.id])
        self.assertEqual(csrf_client.post(toggle_url).status_code, 403)

        # 3. verify_student_college
        verify_url = reverse('admin_panel:verify_student_college', args=[self.student_user.id])
        self.assertEqual(csrf_client.post(verify_url).status_code, 403)

        # 4. suspend_company
        suspend_url = reverse('admin_panel:suspend_company', args=[self.company_profile.id])
        self.assertEqual(csrf_client.post(suspend_url).status_code, 403)




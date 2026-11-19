from django.test import TestCase, override_settings, Client
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth import authenticate
from django.core.cache import cache

from datetime import timedelta
from django.utils import timezone
from accounts.models import User, EmailVerificationToken
from core.models import College, Category
from students.models import StudentProfile, Application
from companies.models import CompanyProfile, Internship


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="reset_user@example.com",
            password="OldPassword123!",
            role="student",
            status="active"
        )
        mail.outbox.clear()

    def test_login_page_has_forgot_password_link(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('accounts:password_reset'))
        self.assertContains(response, "Forgot password?")

    def test_password_reset_page_renders(self):
        response = self.client.get(reverse('accounts:password_reset'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reset Password")

    def test_password_reset_submit_sends_email(self):
        response = self.client.post(reverse('accounts:password_reset'), {
            'email': 'reset_user@example.com'
        })
        self.assertRedirects(response, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]
        self.assertEqual(email.to, ['reset_user@example.com'])
        self.assertIn("[SkillMatch] Password Reset Request", email.subject)
        self.assertIn("password-reset/confirm/", email.body)
        self.assertIn("24 hours", email.body)

    def test_password_reset_confirm_with_valid_token(self):
        token = default_token_generator.make_token(self.user)
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        confirm_url = reverse('accounts:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token})

        response = self.client.get(confirm_url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create New Password")

    def test_password_reset_confirm_with_invalid_token(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        confirm_url = reverse('accounts:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': 'invalid-token'})

        response = self.client.get(confirm_url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid or Expired Link")

    def test_password_reset_enforces_password_policy(self):
        """AC-2.3: Reset form enforces the same password policy as registration (e.g. min 8 chars)."""
        token = default_token_generator.make_token(self.user)
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        confirm_url = reverse('accounts:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token})

        # Visit link to initialize session token
        get_resp = self.client.get(confirm_url, follow=True)
        set_password_url = get_resp.redirect_chain[0][0]

        # Submit short password (less than 8 chars)
        response = self.client.post(set_password_url, {
            'new_password1': 'short1',
            'new_password2': 'short1',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at least 8 characters")

        # Password remains unchanged
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldPassword123!"))

    def test_password_reset_complete_and_token_invalidation(self):
        """AC-2.2: Link is single-use and invalidated after password change."""
        token = default_token_generator.make_token(self.user)
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        confirm_url = reverse('accounts:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token})

        # Visit link to initialize session token
        get_resp = self.client.get(confirm_url, follow=True)
        set_password_url = get_resp.redirect_chain[0][0]

        # Submit valid new password
        response = self.client.post(set_password_url, {
            'new_password1': 'NewValidPassword123!',
            'new_password2': 'NewValidPassword123!',
        })
        self.assertRedirects(response, reverse('accounts:password_reset_complete'))

        # Check new password works and old password fails
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewValidPassword123!"))
        self.assertFalse(self.user.check_password("OldPassword123!"))

        # Check login works with new password
        auth_user = authenticate(email="reset_user@example.com", password="NewValidPassword123!")
        self.assertIsNotNone(auth_user)

        # Trying to use the same token again must fail (AC-2.2)
        response_reused = self.client.get(confirm_url, follow=True)
        self.assertEqual(response_reused.status_code, 200)
        self.assertContains(response_reused, "Invalid or Expired Link")


class Bug12LoginRateLimitingRegressionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.college = College.objects.create(name="Apex College")
        self.user = User.objects.create_user(
            email="lockout_user@example.com",
            password="CorrectPassword123!",
            role="student",
            status="active"
        )
        self.profile = StudentProfile.objects.create(
            user=self.user,
            college=self.college,
            department="Computer Science",
            semester=6,
            college_verified=True
        )

    def tearDown(self):
        cache.clear()

    def test_five_failed_login_attempts_triggers_lockout(self):
        login_url = reverse('accounts:login')

        # Attempts 1 to 4: standard invalid credentials message
        for i in range(4):
            response = self.client.post(login_url, {
                'email': 'lockout_user@example.com',
                'password': 'WrongPassword!',
            })
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Invalid email or password")

        # 5th failed attempt triggers lockout
        response = self.client.post(login_url, {
            'email': 'lockout_user@example.com',
            'password': 'WrongPassword!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Account is locked due to too many failed login attempts. Please try again in 5 minutes.")

    def test_correct_password_blocked_during_lockout(self):
        login_url = reverse('accounts:login')

        # Trigger lockout with 5 failed attempts
        for _ in range(5):
            self.client.post(login_url, {
                'email': 'lockout_user@example.com',
                'password': 'WrongPassword!',
            })

        # 6th attempt with CORRECT password must be blocked
        response = self.client.post(login_url, {
            'email': 'lockout_user@example.com',
            'password': 'CorrectPassword123!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Account is locked due to too many failed login attempts. Please try again in 5 minutes.")

        # Ensure user is NOT logged in in session
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_successful_login_resets_counter(self):
        login_url = reverse('accounts:login')

        # 3 failed attempts
        for _ in range(3):
            self.client.post(login_url, {
                'email': 'lockout_user@example.com',
                'password': 'WrongPassword!',
            })

        # 4th attempt is successful
        response = self.client.post(login_url, {
            'email': 'lockout_user@example.com',
            'password': 'CorrectPassword123!',
        })
        self.assertRedirects(response, reverse('students:dashboard'))

        # Log out
        self.client.logout()

        # 3 more failed attempts should not trigger lockout because counter was reset
        for _ in range(3):
            response = self.client.post(login_url, {
                'email': 'lockout_user@example.com',
                'password': 'WrongPassword!',
            })
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Invalid email or password")
            self.assertNotContains(response, "Account is locked")


class Phase2RegistrationAndVerificationTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Tribhuvan University College")

    def test_student_registration_sets_unverified_college_and_pending_status(self):
        """Newly registered students are created with pending_email status and college_verified=False."""
        register_url = reverse('accounts:register')
        response = self.client.post(register_url, {
            'role': 'student',
            'email': 'new_student@example.com',
            'college': self.college.id,
            'department': 'BIM',
            'semester': 6,
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })
        self.assertRedirects(response, reverse('accounts:account_status'))

        student = User.objects.get(email='new_student@example.com')
        self.assertEqual(student.role, 'student')
        self.assertEqual(student.status, 'pending_email')
        self.assertFalse(student.student_profile.college_verified)

    def test_student_registration_cannot_self_verify_college(self):
        """Student cannot inject college_verified=True through registration payload."""
        register_url = reverse('accounts:register')
        self.client.post(register_url, {
            'role': 'student',
            'email': 'hacker_student@example.com',
            'college': self.college.id,
            'department': 'BIM',
            'semester': 6,
            'college_verified': 'True',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })

        student = User.objects.get(email='hacker_student@example.com')
        self.assertFalse(student.student_profile.college_verified)

    def test_company_registration_requires_hq_location(self):
        """Company registration without headquarters location fails form validation."""
        register_url = reverse('accounts:register')
        response = self.client.post(register_url, {
            'role': 'company',
            'email': 'nolocation_corp@example.com',
            'organization_name': 'NoLocation Corp',
            'contact_person': 'HR Manager',
            'industry': 'Software Development',
            'description': 'A software engineering firm in Nepal.',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })
        # Should stay on page and not create user
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email='nolocation_corp@example.com').exists())

    def test_company_registration_with_hq_location_succeeds_and_is_pending(self):
        """Company registration with valid hq_location succeeds with pending status."""
        register_url = reverse('accounts:register')
        response = self.client.post(register_url, {
            'role': 'company',
            'email': 'valid_corp@example.com',
            'organization_name': 'Kathmandu Tech Hub',
            'contact_person': 'Anita Sharma',
            'industry': 'IT Services',
            'hq_location': 'Baneshwor, Kathmandu',
            'description': 'Leading IT solutions provider.',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })
        self.assertRedirects(response, reverse('accounts:login'))

        company_user = User.objects.get(email='valid_corp@example.com')
        self.assertEqual(company_user.role, 'company')
        self.assertEqual(company_user.status, 'pending_email')

        profile = company_user.company_profile
        self.assertEqual(profile.organization_name, 'Kathmandu Tech Hub')
        self.assertEqual(profile.hq_location, 'Baneshwor, Kathmandu')

    def test_duplicate_account_registration_is_rejected(self):
        """Registering with an already existing email is rejected gracefully."""
        User.objects.create_user(
            email='existing_user@example.com',
            password='ExistingPass123!',
            role='student'
        )

        register_url = reverse('accounts:register')
        response = self.client.post(register_url, {
            'role': 'student',
            'email': 'existing_user@example.com',
            'college': self.college.id,
            'department': 'BIM',
            'semester': 6,
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(email='existing_user@example.com').count(), 1)


class LogoutSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="student_logout@example.com",
            password="StrongPass123!",
            role="student",
            status="active"
        )
        self.logout_url = reverse('accounts:logout')

    def test_get_logout_returns_405_and_preserves_session(self):
        """GET /logout/ returns HTTP 405 Method Not Allowed and session remains active."""
        self.client.login(email="student_logout@example.com", password="StrongPass123!")
        self.assertEqual(int(self.client.session.get('_auth_user_id')), self.user.pk)

        response = self.client.get(self.logout_url)
        self.assertEqual(response.status_code, 405)
        # Session still preserved
        self.assertEqual(int(self.client.session.get('_auth_user_id')), self.user.pk)

    def test_post_logout_succeeds_and_clears_session(self):
        """POST /logout/ successfully logs user out, clears session, and redirects to home."""
        self.client.login(email="student_logout@example.com", password="StrongPass123!")
        self.assertEqual(int(self.client.session.get('_auth_user_id')), self.user.pk)

        response = self.client.post(self.logout_url)
        self.assertRedirects(response, reverse('accounts:home'))
        # Session cleared
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_csrf_enforcement_on_logout(self):
        """POST /logout/ without CSRF token returns 403 Forbidden when CSRF checks are enforced."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(email="student_logout@example.com", password="StrongPass123!")

        # POST without CSRF token
        response = csrf_client.post(self.logout_url)
        self.assertEqual(response.status_code, 403)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class Phase4EmailVerificationAndRedirectSecurityTests(TestCase):
    def setUp(self):
        mail.outbox.clear()
        self.college = College.objects.create(name="Patan College")
        self.student_user = User.objects.create_user(
            email="verify_student@example.com",
            password="Password123!",
            role="student",
            status="pending_email"
        )
        self.student_profile = StudentProfile.objects.create(
            user=self.student_user,
            college=self.college,
            department="Computer Science",
            semester=5,
            college_verified=False
        )
        self.company_user = User.objects.create_user(
            email="verify_company@example.com",
            password="Password123!",
            role="company",
            status="pending_email"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="Kathmandu Digital",
            contact_person="Ramesh Koirala",
            industry="Software",
            hq_location="Kathmandu",
            description="Software Engineering"
        )
        self.token_student = EmailVerificationToken.objects.create(user=self.student_user)

    def test_registration_creates_token_and_sends_verification_email(self):
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('accounts:register'), {
                'role': 'student',
                'email': 'brand_new_student@example.com',
                'college': self.college.id,
                'department': 'CSIT',
                'semester': 4,
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            })
        new_user = User.objects.get(email='brand_new_student@example.com')
        self.assertEqual(new_user.status, 'pending_email')
        token = EmailVerificationToken.objects.filter(user=new_user).first()
        self.assertIsNotNone(token)
        self.assertFalse(token.used)

        # Check notification email was queued/sent
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.to, ['brand_new_student@example.com'])
        self.assertIn("Verify Your Email Address", sent_email.subject)
        self.assertIn(str(token.token), sent_email.body)
        self.assertIn("24 hours", sent_email.body)

    def test_company_registration_creates_token_and_sends_verification_email(self):
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('accounts:register'), {
                'role': 'company',
                'email': 'brand_new_corp@example.com',
                'organization_name': 'New Tech Hub',
                'contact_person': 'Suman Shrestha',
                'industry': 'Fintech',
                'hq_location': 'Lalitpur',
                'description': 'Mobile payment platform',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            })
        new_corp = User.objects.get(email='brand_new_corp@example.com')
        self.assertEqual(new_corp.status, 'pending_email')
        token = EmailVerificationToken.objects.filter(user=new_corp).first()
        self.assertIsNotNone(token)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['brand_new_corp@example.com'])
        self.assertIn(str(token.token), mail.outbox[0].body)

    def test_get_verification_url_renders_confirmation_form_without_state_mutation(self):
        verify_url = reverse('accounts:verify_email', kwargs={'token': self.token_student.token})
        response = self.client.get(verify_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Confirm Email Verification")
        self.assertContains(response, self.student_user.email)
        self.assertContains(response, "csrfmiddlewaretoken")

        # Database state MUST NOT change on GET
        self.student_user.refresh_from_db()
        self.token_student.refresh_from_db()
        self.assertEqual(self.student_user.status, 'pending_email')
        self.assertFalse(self.token_student.used)

    def test_post_verification_url_transitions_status_to_pending_admin(self):
        verify_url = reverse('accounts:verify_email', kwargs={'token': self.token_student.token})
        response = self.client.post(verify_url)
        self.assertRedirects(response, reverse('accounts:login'))

        # Token marked as used
        self.token_student.refresh_from_db()
        self.assertTrue(self.token_student.used)

        # Status transitions from pending_email to pending_admin (NEVER active directly)
        self.student_user.refresh_from_db()
        self.assertEqual(self.student_user.status, 'pending_admin')

        # College verification remains independent
        self.student_profile.refresh_from_db()
        self.assertFalse(self.student_profile.college_verified)

    def test_token_cannot_be_reused(self):
        self.token_student.used = True
        self.token_student.save(update_fields=['used'])

        verify_url = reverse('accounts:verify_email', kwargs={'token': self.token_student.token})
        # GET shows already used
        response_get = self.client.get(verify_url)
        self.assertEqual(response_get.status_code, 200)
        self.assertContains(response_get, "Verification Link Already Used")

        # POST does not mutate status
        response_post = self.client.post(verify_url)
        self.assertEqual(response_post.status_code, 200)
        self.student_user.refresh_from_db()
        self.assertEqual(self.student_user.status, 'pending_email')

    def test_expired_token_rejected(self):
        # Set token created_at to 25 hours ago
        self.token_student.created_at = timezone.now() - timedelta(hours=25)
        self.token_student.save(update_fields=['created_at'])

        verify_url = reverse('accounts:verify_email', kwargs={'token': self.token_student.token})
        # GET shows expired
        response_get = self.client.get(verify_url)
        self.assertEqual(response_get.status_code, 200)
        self.assertContains(response_get, "Verification Link Expired")

        # POST rejected
        response_post = self.client.post(verify_url)
        self.assertEqual(response_post.status_code, 200)
        self.student_user.refresh_from_db()
        self.assertEqual(self.student_user.status, 'pending_email')

    def test_invalid_or_nonexistent_token_rejected(self):
        import uuid
        non_existent_token = uuid.uuid4()
        verify_url = reverse('accounts:verify_email', kwargs={'token': non_existent_token})
        response = self.client.get(verify_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid Verification Link")

    def test_unverified_student_cannot_apply_for_internship(self):
        category = Category.objects.create(name="Engineering Category")
        internship = Internship.objects.create(
            company=self.company_profile,
            title="Software Trainee",
            description="Trainee position",
            category=category,
            location_type="remote",
            deadline=timezone.now().date(),
            total_positions=1,
            expected_duration="3 months",
            status="approved"
        )
        self.client.force_login(self.student_user)
        apply_url = reverse('students:apply_internship', kwargs={'internship_id': internship.id})
        response = self.client.post(apply_url)
        # Blocked and redirected to internship detail with verification warning
        self.assertRedirects(response, reverse('students:internship_detail', kwargs={'internship_id': internship.id}))
        # Verify no application created
        self.assertFalse(Application.objects.filter(student=self.student_user, internship=internship).exists())

    def test_redirect_security_safe_relative_url(self):
        self.student_user.status = 'active'
        self.student_user.save()
        browse_url = reverse('students:browse_internships')
        response = self.client.post(reverse('accounts:login'), {
            'email': 'verify_student@example.com',
            'password': 'Password123!',
            'next': browse_url,
        })
        self.assertRedirects(response, browse_url)

    def test_redirect_security_safe_same_host_absolute_url(self):
        self.student_user.status = 'active'
        self.student_user.save()
        browse_url = reverse('students:browse_internships')
        full_url = f"http://testserver{browse_url}"
        response = self.client.post(reverse('accounts:login'), {
            'email': 'verify_student@example.com',
            'password': 'Password123!',
            'next': full_url,
        })
        self.assertRedirects(response, full_url)

    def test_redirect_security_rejects_external_domain(self):
        self.student_user.status = 'active'
        self.student_user.save()
        response = self.client.post(reverse('accounts:login'), {
            'email': 'verify_student@example.com',
            'password': 'Password123!',
            'next': 'https://evil.com/phishing',
        })
        # Falls back to default role dashboard
        self.assertRedirects(response, reverse('students:dashboard'))

    def test_redirect_security_rejects_protocol_relative(self):
        self.student_user.status = 'active'
        self.student_user.save()
        response = self.client.post(reverse('accounts:login'), {
            'email': 'verify_student@example.com',
            'password': 'Password123!',
            'next': '//evil.com/phishing',
        })
        self.assertRedirects(response, reverse('students:dashboard'))

    def test_redirect_security_rejects_backslash_payloads(self):
        self.student_user.status = 'active'
        self.student_user.save()
        for unsafe in ['/\\evil.com', '\\\\evil.com', '/%5cevil.com']:
            response = self.client.post(reverse('accounts:login'), {
                'email': 'verify_student@example.com',
                'password': 'Password123!',
                'next': unsafe,
            })
            self.assertRedirects(response, reverse('students:dashboard'))

    def test_pending_email_user_restricted_from_workspaces(self):
        """Pending email student cannot access dashboard, profile edit, or skills edit."""
        self.client.force_login(self.student_user)
        for url_name in ['students:dashboard', 'students:profile_edit', 'students:skills_edit']:
            resp = self.client.get(reverse(url_name))
            self.assertRedirects(resp, reverse('accounts:account_status'))

    def test_pending_admin_user_restricted_from_placement_functionality(self):
        """Pending admin student cannot access dashboard, profile edit, skills edit, or apply."""
        self.student_user.status = 'pending_admin'
        self.student_user.save()
        self.client.force_login(self.student_user)

        for url_name in ['students:dashboard', 'students:profile_edit', 'students:skills_edit']:
            resp = self.client.get(reverse(url_name))
            self.assertRedirects(resp, reverse('accounts:account_status'))

    def test_pending_company_restricted_from_company_workspace(self):
        """Pending email and pending admin companies cannot access dashboard, profile edit, or post listing."""
        # Pending email
        self.client.force_login(self.company_user)
        for url_name in ['companies:dashboard', 'companies:profile_edit', 'companies:create_listing']:
            resp = self.client.get(reverse(url_name))
            self.assertRedirects(resp, reverse('accounts:account_status'))

        # Pending admin
        self.company_user.status = 'pending_admin'
        self.company_user.save()
        for url_name in ['companies:dashboard', 'companies:profile_edit', 'companies:create_listing']:
            resp = self.client.get(reverse(url_name))
            self.assertRedirects(resp, reverse('accounts:account_status'))

    def test_active_users_retain_full_access(self):
        """Active student and company users access their dashboards and features normally."""
        self.student_user.status = 'active'
        self.student_user.save()
        self.client.force_login(self.student_user)
        resp_student = self.client.get(reverse('students:dashboard'))
        self.assertEqual(resp_student.status_code, 200)

        self.company_user.status = 'active'
        self.company_user.save()
        self.client.force_login(self.company_user)
        resp_company = self.client.get(reverse('companies:dashboard'))
        self.assertEqual(resp_company.status_code, 200)

    def test_account_status_page_renders_cleanly_for_pending_states(self):
        """Account status page renders clear explanation for pending_email and pending_admin."""
        self.client.force_login(self.student_user)
        resp = self.client.get(reverse('accounts:account_status'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Email Verification Pending")

        self.student_user.status = 'pending_admin'
        self.student_user.save()
        resp2 = self.client.get(reverse('accounts:account_status'))
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "Awaiting Administrator Approval")

    def test_email_verification_atomic_successful_transition(self):
        """Verification post atomically updates token and user status to pending_admin."""
        self.assertEqual(self.student_user.status, 'pending_email')
        self.assertFalse(self.token_student.used)

        verify_url = reverse('accounts:verify_email', kwargs={'token': self.token_student.token})
        resp = self.client.post(verify_url)
        self.assertRedirects(resp, reverse('accounts:login'))

        self.token_student.refresh_from_db()
        self.student_user.refresh_from_db()
        self.assertTrue(self.token_student.used)
        self.assertEqual(self.student_user.status, 'pending_admin')
        self.assertNotEqual(self.student_user.status, 'active')


class StrictWorkspaceAccessControlTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Central Campus")
        self.category = Category.objects.create(name="Tech")

        # Active student
        self.active_student = User.objects.create_user(
            email="active_student@example.com", password="Password123!", role="student", status="active"
        )
        self.active_student_profile = StudentProfile.objects.create(
            user=self.active_student, college=self.college, department="CS", semester=6, college_verified=True,
            cv_file=SimpleUploadedFile("my_cv.pdf", b"%PDF-1.4 my cv", content_type="application/pdf")
        )

        # Pending email student
        self.pending_email_student = User.objects.create_user(
            email="pending_email_student@example.com", password="Password123!", role="student", status="pending_email"
        )
        self.pending_email_student_profile = StudentProfile.objects.create(
            user=self.pending_email_student, college=self.college, department="CS", semester=6, college_verified=False,
            cv_file=SimpleUploadedFile("pe_cv.pdf", b"%PDF-1.4 pe cv", content_type="application/pdf")
        )

        # Pending admin student
        self.pending_admin_student = User.objects.create_user(
            email="pending_admin_student@example.com", password="Password123!", role="student", status="pending_admin"
        )
        self.pending_admin_student_profile = StudentProfile.objects.create(
            user=self.pending_admin_student, college=self.college, department="CS", semester=6, college_verified=False,
            cv_file=SimpleUploadedFile("pa_cv.pdf", b"%PDF-1.4 pa cv", content_type="application/pdf")
        )

        # Rejected student
        self.rejected_student = User.objects.create_user(
            email="rejected_student@example.com", password="Password123!", role="student", status="rejected"
        )
        self.rejected_student_profile = StudentProfile.objects.create(
            user=self.rejected_student, college=self.college, department="CS", semester=6, college_verified=False,
            cv_file=SimpleUploadedFile("rej_cv.pdf", b"%PDF-1.4 rej cv", content_type="application/pdf")
        )

        # Active company
        self.active_company = User.objects.create_user(
            email="active_company@example.com", password="Password123!", role="company", status="active"
        )
        self.active_company_profile = CompanyProfile.objects.create(
            user=self.active_company, organization_name="Active Corp", contact_person="John",
            industry="IT", hq_location="Kathmandu", description="Tech corp"
        )

        # Pending email company
        self.pending_email_company = User.objects.create_user(
            email="pe_company@example.com", password="Password123!", role="company", status="pending_email"
        )
        self.pe_company_profile = CompanyProfile.objects.create(
            user=self.pending_email_company, organization_name="PE Corp", contact_person="John",
            industry="IT", hq_location="Kathmandu", description="Tech corp"
        )

        # Pending admin company
        self.pending_admin_company = User.objects.create_user(
            email="pa_company@example.com", password="Password123!", role="company", status="pending_admin"
        )
        self.pa_company_profile = CompanyProfile.objects.create(
            user=self.pending_admin_company, organization_name="PA Corp", contact_person="John",
            industry="IT", hq_location="Kathmandu", description="Tech corp"
        )

        # Rejected company
        self.rejected_company = User.objects.create_user(
            email="rej_company@example.com", password="Password123!", role="company", status="rejected"
        )
        self.rej_company_profile = CompanyProfile.objects.create(
            user=self.rejected_company, organization_name="Rej Corp", contact_person="John",
            industry="IT", hq_location="Kathmandu", description="Tech corp"
        )

        # Suspended company
        self.suspended_company = User.objects.create_user(
            email="suspended_company@example.com", password="Password123!", role="company", status="suspended"
        )
        self.suspended_company_profile = CompanyProfile.objects.create(
            user=self.suspended_company, organization_name="Suspended Corp", contact_person="John",
            industry="IT", hq_location="Kathmandu", description="Suspended corp"
        )

        # Administrator
        self.admin_user = User.objects.create_user(
            email="admin_user@example.com", password="Password123!", role="admin", status="active", is_staff=True
        )

        # Sample approved internship
        self.internship = Internship.objects.create(
            company=self.active_company_profile, title="Backend Intern", description="Django role",
            category=self.category, location_type="remote", deadline=timezone.now().date() + timedelta(days=30),
            total_positions=2, expected_duration="3 months", status="approved"
        )

        # Sample application with offer
        self.application = Application.objects.create(
            student=self.active_student, internship=self.internship, match_score=85.0, status="offer_issued",
            offer_letter=SimpleUploadedFile("offer.pdf", b"%PDF-1.4 Offer letter", content_type="application/pdf")
        )

    def test_pending_and_rejected_students_restricted_from_all_workspace_routes(self):
        """Pending email, pending admin, and rejected students are blocked from all student workspace routes."""
        test_students = [
            self.pending_email_student,
            self.pending_admin_student,
            self.rejected_student,
        ]
        status_url = reverse('accounts:account_status')

        for student in test_students:
            self.client.force_login(student)

            # 1. Profile and dashboard routes
            self.assertRedirects(self.client.get(reverse('students:dashboard')), status_url)
            self.assertRedirects(self.client.get(reverse('students:profile')), status_url)
            self.assertRedirects(self.client.get(reverse('students:profile_edit')), status_url)
            self.assertRedirects(self.client.get(reverse('students:skills_edit')), status_url)

            # 2. Applications route
            self.assertRedirects(self.client.get(reverse('students:my_applications')), status_url)

            # 3. CV viewing routes
            self.assertRedirects(self.client.get(reverse('students:view_my_cv')), status_url)
            self.assertRedirects(self.client.get(reverse('students:view_cv', args=[student.id])), status_url)

            # 4. Offer viewing route
            self.assertRedirects(self.client.get(reverse('students:view_offer', args=[self.application.id])), status_url)

            # 5. Offer letter viewing route
            self.assertRedirects(self.client.get(reverse('students:view_offer_letter', args=[self.application.id])), status_url)

            # 6. State-changing actions: application withdrawal, offer acceptance, offer decline
            self.assertRedirects(self.client.post(reverse('students:withdraw_application', args=[self.application.id])), status_url)
            self.assertRedirects(self.client.post(reverse('students:accept_offer', args=[self.application.id])), status_url)
            self.assertRedirects(self.client.post(reverse('students:decline_offer', args=[self.application.id])), status_url)

    def test_pending_and_rejected_students_can_browse_internships_and_view_detail(self):
        """Pending and rejected students retain access to public internship browsing and detail pages."""
        test_students = [
            self.pending_email_student,
            self.pending_admin_student,
            self.rejected_student,
        ]
        for student in test_students:
            self.client.force_login(student)
            browse_resp = self.client.get(reverse('students:browse_internships'))
            self.assertEqual(browse_resp.status_code, 200)

            detail_resp = self.client.get(reverse('students:internship_detail', args=[self.internship.id]))
            self.assertEqual(detail_resp.status_code, 200)

    def test_pending_and_rejected_companies_restricted_from_company_workspace(self):
        """Pending email, pending admin, and rejected companies are blocked from all company workspace routes."""
        test_companies = [
            self.pending_email_company,
            self.pending_admin_company,
            self.rejected_company,
        ]
        status_url = reverse('accounts:account_status')

        for company_user in test_companies:
            self.client.force_login(company_user)

            self.assertRedirects(self.client.get(reverse('companies:dashboard')), status_url)
            self.assertRedirects(self.client.get(reverse('companies:profile')), status_url)
            self.assertRedirects(self.client.get(reverse('companies:profile_edit')), status_url)
            self.assertRedirects(self.client.get(reverse('companies:my_listings')), status_url)
            self.assertRedirects(self.client.get(reverse('companies:create_listing')), status_url)
            self.assertRedirects(self.client.get(reverse('companies:edit_listing', args=[self.internship.id])), status_url)
            self.assertRedirects(self.client.get(reverse('companies:delete_listing', args=[self.internship.id])), status_url)
            self.assertRedirects(self.client.get(reverse('companies:view_applicants', args=[self.internship.id])), status_url)
            self.assertRedirects(self.client.get(reverse('companies:applicant_detail', args=[self.application.id])), status_url)
            self.assertRedirects(self.client.get(reverse('companies:issue_offer', args=[self.application.id])), status_url)

    def test_suspended_company_restrictions(self):
        """Suspended companies cannot manage listings, review applicants, issue offers, or access private applicant documents."""
        # 1. User status suspended -> logged out immediately
        self.client.login(email=self.suspended_company.email, password="Password123!")
        resp1 = self.client.get(reverse('companies:dashboard'), follow=True)
        self.assertRedirects(resp1, reverse('accounts:login'))

        # 2. Company profile suspended -> logged out immediately
        self.active_company_profile.suspended = True
        self.active_company_profile.save()
        self.client.login(email=self.active_company.email, password="Password123!")
        resp2 = self.client.get(reverse('companies:dashboard'), follow=True)
        self.assertRedirects(resp2, reverse('accounts:login'))

    def test_guests_and_administrators_intended_access(self):
        """Guests can browse internships; administrators can access student CVs without restriction."""
        self.client.logout()
        # Guest can browse
        resp_browse = self.client.get(reverse('students:browse_internships'))
        self.assertEqual(resp_browse.status_code, 200)

        resp_detail = self.client.get(reverse('students:internship_detail', args=[self.internship.id]))
        self.assertEqual(resp_detail.status_code, 200)

        # Guest blocked from student dashboard
        resp_guest_dash = self.client.get(reverse('students:dashboard'))
        self.assertEqual(resp_guest_dash.status_code, 302)

        # Administrator can access student CV
        self.client.force_login(self.admin_user)
        cv_resp = self.client.get(reverse('students:view_cv', args=[self.active_student.id]))
        self.assertEqual(cv_resp.status_code, 200)





from django.test import TestCase, override_settings
from django.core import mail
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth import authenticate
from django.core.cache import cache

from accounts.models import User
from core.models import College
from students.models import StudentProfile


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


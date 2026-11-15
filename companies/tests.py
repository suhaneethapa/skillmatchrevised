from datetime import date, timedelta
from django.test import TestCase, override_settings
from django.core import mail
from django.urls import reverse
from django.core.exceptions import ValidationError

from accounts.models import User
from core.models import College, Category, Skill
from companies.models import CompanyProfile, Internship, InternshipSkill
from students.models import StudentProfile, Application


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class Bug01RejectApplicantRegressionTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Prime College")
        self.category = Category.objects.create(name="Engineering")

        # Create student
        self.student_user = User.objects.create_user(
            email="applicant_student@demo.local",
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

        # Create company
        self.company_user = User.objects.create_user(
            email="hiring_company@demo.local",
            password="DemoPassword123!",
            role="company",
            status="active"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="Alpha Tech Pvt. Ltd.",
            contact_person="HR Manager",
            industry="IT",
            description="Leading software company"
        )

        # Create internship
        self.internship = Internship.objects.create(
            company=self.company_profile,
            title="Backend Engineering Intern",
            description="Python & Django internship",
            category=self.category,
            location_type="hybrid",
            deadline=date.today(),
            total_positions=2,
            expected_duration="3 months",
            status="approved"
        )

        # Create application
        self.application = Application.objects.create(
            student=self.student_user,
            internship=self.internship,
            match_score=80.0,
            status="pending"
        )
        mail.outbox.clear()

    def test_applicants_page_has_reject_action(self):
        """Applicants table must render a Reject action button for pending applicants."""
        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        url = reverse('companies:view_applicants', args=[self.internship.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        reject_url = reverse('companies:reject_applicant', args=[self.application.id])
        self.assertContains(response, reject_url)
        self.assertContains(response, "Reject")

    def test_reject_page_renders_form_with_required_reasons(self):
        """GET reject page must render the 5 required reasons as choices."""
        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        reject_url = reverse('companies:reject_applicant', args=[self.application.id])
        response = self.client.get(reject_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Skills mismatch")
        self.assertContains(response, "Position filled")
        self.assertContains(response, "Stronger candidates")
        self.assertContains(response, "No response from candidate")
        self.assertContains(response, "Other")

    def test_reject_without_reason_fails(self):
        """Rejecting without selecting a valid reason must be blocked with validation error."""
        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        reject_url = reverse('companies:reject_applicant', args=[self.application.id])
        response = self.client.post(reject_url, {
            'rejection_reason': '',
            'feedback': 'Missing skills'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please select a valid rejection reason")

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'pending')

    def test_reject_with_valid_reason_and_notification(self):
        """Valid rejection must update state, store reason, and send notification email."""
        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        reject_url = reverse('companies:reject_applicant', args=[self.application.id])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reject_url, {
                'rejection_reason': 'Skills mismatch',
                'feedback': 'Candidate lacked necessary Django framework knowledge.'
            })

        self.assertRedirects(response, reverse('companies:view_applicants', args=[self.internship.id]))

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'rejected')
        self.assertEqual(self.application.rejection_reason, 'Skills mismatch')
        self.assertEqual(self.application.rejection_feedback, 'Candidate lacked necessary Django framework knowledge.')

        # Verify email notification
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, [self.student_user.email])
        self.assertIn("Reason: Skills mismatch", email.body)
        self.assertIn("Candidate lacked necessary Django framework knowledge.", email.body)

    def test_student_sees_rejection_reason_in_dashboard(self):
        """Student must see rejection reason in My Applications section on student dashboard."""
        self.application.status = 'rejected'
        self.application.rejection_reason = 'Stronger candidates'
        self.application.rejection_feedback = 'Other applicants had relevant prior experience.'
        self.application.save()

        self.client.login(email=self.student_user.email, password="DemoPassword123!")
        response = self.client.get(reverse('students:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Stronger candidates")
        self.assertContains(response, "Other applicants had relevant prior experience.")


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class Bug06LockListingSkillsRegressionTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Prime College")
        self.category = Category.objects.create(name="Software Engineering")

        self.python_skill = Skill.objects.create(name="Python", category=self.category)
        self.django_skill = Skill.objects.create(name="Django", category=self.category)
        self.docker_skill = Skill.objects.create(name="Docker", category=self.category)

        # Company
        self.company_user = User.objects.create_user(
            email="company_lock@demo.local",
            password="DemoPassword123!",
            role="company",
            status="active"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="Locked Skills Inc.",
            contact_person="HR Manager",
            industry="Software",
            description="Testing skills lock"
        )

        # Internship
        self.internship = Internship.objects.create(
            company=self.company_profile,
            title="Backend Engineer",
            description="Django backend role",
            category=self.category,
            location_type="remote",
            deadline=date.today(),
            total_positions=2,
            expected_duration="3 months",
            status="approved"
        )
        self.is_python = InternshipSkill.objects.create(internship=self.internship, skill=self.python_skill, is_required=True)
        self.is_django = InternshipSkill.objects.create(internship=self.internship, skill=self.django_skill, is_required=False)

        # Student
        self.student_user = User.objects.create_user(
            email="applicant_lock@demo.local",
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

    def test_skills_unlocked_when_no_applications(self):
        """When an internship has zero applications, skills are unlocked and can be modified."""
        self.assertFalse(self.internship.skills_locked)

        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        url = reverse('companies:edit_listing', args=[self.internship.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Skills Locked")

        # Company modifies skills
        post_data = {
            'title': 'Backend Engineer',
            'category': self.category.id,
            'description': 'Updated description',
            'location_type': 'remote',
            'total_positions': 2,
            'deadline': date.today().strftime('%Y-%m-%d'),
            'expected_duration': '3 months',
            'required_skills': [self.docker_skill.id],
            'preferred_skills': [self.python_skill.id],
        }
        post_resp = self.client.post(url, post_data)
        self.assertRedirects(post_resp, reverse('companies:my_listings'))

        req_skills = list(self.internship.internship_skills.filter(is_required=True).values_list('skill__name', flat=True))
        self.assertEqual(req_skills, ['Docker'])

    def test_skills_locked_when_application_exists(self):
        """Once first application arrives, skills_locked is True and edit page displays warning."""
        Application.objects.create(
            student=self.student_user,
            internship=self.internship,
            match_score=100.0,
            status='pending'
        )
        self.assertTrue(self.internship.skills_locked)

        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        url = reverse('companies:edit_listing', args=[self.internship.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Skills Locked")
        self.assertContains(response, "Skill requirements cannot be modified")

    def test_edit_listing_blocks_modifying_skills_when_applications_exist(self):
        """Attempting to change skills after receiving an application must be blocked with an explanation."""
        Application.objects.create(
            student=self.student_user,
            internship=self.internship,
            match_score=100.0,
            status='pending'
        )

        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        url = reverse('companies:edit_listing', args=[self.internship.id])

        # Attempt to change required skills to Docker
        post_data = {
            'title': 'Backend Engineer (Updated)',
            'category': self.category.id,
            'description': 'Trying to modify skills after applications arrived',
            'location_type': 'remote',
            'total_positions': 2,
            'deadline': date.today().strftime('%Y-%m-%d'),
            'expected_duration': '3 months',
            'required_skills': [self.docker_skill.id],
            'preferred_skills': [],
        }
        response = self.client.post(url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Listing skills are locked because applications have already been received")

        # Original skills remain completely unchanged
        req_skills = list(self.internship.internship_skills.filter(is_required=True).values_list('skill__name', flat=True))
        self.assertEqual(req_skills, ['Python'])

    def test_model_clean_and_delete_block_modifying_skills_when_applications_exist(self):
        """Model-level clean() and delete() block creating or deleting InternshipSkill rows when applications exist."""
        Application.objects.create(
            student=self.student_user,
            internship=self.internship,
            match_score=100.0,
            status='pending'
        )

        # Attempt to add new skill via model
        new_iskill = InternshipSkill(internship=self.internship, skill=self.docker_skill, is_required=True)
        with self.assertRaises(ValidationError):
            new_iskill.full_clean()

        # Attempt to delete existing skill
        with self.assertRaises(ValidationError):
            self.is_python.delete()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class Bug07StateMachineAndAtomicAcceptRegressionTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Prime College")
        self.category = Category.objects.create(name="Web Dev")
        self.python_skill = Skill.objects.create(name="Python", category=self.category)

        # Company
        self.company_user = User.objects.create_user(
            email="company_sm@demo.local",
            password="DemoPassword123!",
            role="company",
            status="active"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="State Machine Corp",
            contact_person="HR",
            industry="IT",
            description="Testing state guards"
        )

        # Internship with 1 position
        self.internship = Internship.objects.create(
            company=self.company_profile,
            title="Single Slot Python Intern",
            description="Testing position race condition",
            category=self.category,
            location_type="remote",
            deadline=date.today() + timedelta(days=7),
            total_positions=1,
            expected_duration="3 months",
            status="approved"
        )
        InternshipSkill.objects.create(internship=self.internship, skill=self.python_skill, is_required=True)

        # Student 1
        self.student_user1 = User.objects.create_user(
            email="student1_sm@demo.local",
            password="DemoPassword123!",
            role="student",
            status="active"
        )
        self.student_profile1 = StudentProfile.objects.create(
            user=self.student_user1,
            college=self.college,
            department="BIM",
            semester=6
        )
        self.app1 = Application.objects.create(
            student=self.student_user1,
            internship=self.internship,
            match_score=100.0,
            status='pending'
        )

        # Student 2
        self.student_user2 = User.objects.create_user(
            email="student2_sm@demo.local",
            password="DemoPassword123!",
            role="student",
            status="active"
        )
        self.student_profile2 = StudentProfile.objects.create(
            user=self.student_user2,
            college=self.college,
            department="BIM",
            semester=6
        )
        self.app2 = Application.objects.create(
            student=self.student_user2,
            internship=self.internship,
            match_score=100.0,
            status='pending'
        )

    def test_company_cannot_issue_offer_for_closed_or_expired_listing(self):
        """Company cannot issue an offer when listing is closed or past deadline."""
        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        offer_url = reverse('companies:issue_offer', args=[self.app1.id])

        # Listing closed
        self.internship.status = 'closed'
        self.internship.save()
        resp_closed = self.client.post(offer_url, {}, follow=True)
        self.assertContains(resp_closed, "Cannot issue offers for an internship listing that is not open")
        self.app1.refresh_from_db()
        self.assertEqual(self.app1.status, 'pending')

        # Listing expired
        self.internship.status = 'approved'
        self.internship.deadline = date.today() - timedelta(days=1)
        self.internship.save()
        resp_expired = self.client.post(offer_url, {}, follow=True)
        self.assertContains(resp_expired, "Cannot issue offers because this internship listing deadline has passed")
        self.app1.refresh_from_db()
        self.assertEqual(self.app1.status, 'pending')

    def test_company_cannot_issue_offer_for_non_pending_application(self):
        """Company cannot issue an offer to a rejected or withdrawn application."""
        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        offer_url = reverse('companies:issue_offer', args=[self.app1.id])

        self.app1.status = 'rejected'
        self.app1.save()
        response = self.client.post(offer_url, {}, follow=True)
        self.assertContains(response, "Cannot issue an offer for an application")
        self.assertContains(response, "Rejected")
        self.app1.refresh_from_db()
        self.assertEqual(self.app1.status, 'rejected')
        self.app1.refresh_from_db()
        self.assertEqual(self.app1.status, 'rejected')

    def test_student_cannot_accept_when_positions_are_filled(self):
        """Student cannot accept an offer if remaining positions are 0 (e.g. concurrent race condition)."""
        # Both students received offers
        self.app1.status = 'offer_issued'
        self.app1.save()
        self.app2.status = 'offer_issued'
        self.app2.save()

        # Student 1 accepts first slot
        self.client.login(email=self.student_user1.email, password="DemoPassword123!")
        accept_url1 = reverse('students:accept_offer', args=[self.app1.id])
        resp1 = self.client.get(accept_url1, follow=True)
        self.assertContains(resp1, "Congratulations! You have accepted the offer")
        self.app1.refresh_from_db()
        self.assertEqual(self.app1.status, 'accepted')

        # Internship is now closed and has 0 remaining positions
        self.internship.refresh_from_db()
        self.assertEqual(self.internship.remaining_positions, 0)

        # Student 2 tries to accept the now filled slot
        self.client.login(email=self.student_user2.email, password="DemoPassword123!")
        accept_url2 = reverse('students:accept_offer', args=[self.app2.id])
        resp2 = self.client.get(accept_url2, follow=True)
        self.assertContains(resp2, "all positions for this internship have already been filled")
        self.app2.refresh_from_db()
        self.assertNotEqual(self.app2.status, 'accepted')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class Bug11ListingValidationRegressionTests(TestCase):
    def setUp(self):
        self.college = College.objects.create(name="Prime College")
        self.category = Category.objects.create(name="Design")
        self.ui_skill = Skill.objects.create(name="UI Design", category=self.category)

        # Company
        self.company_user = User.objects.create_user(
            email="company_valid@demo.local",
            password="DemoPassword123!",
            role="company",
            status="active"
        )
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            organization_name="Validation Design Studio",
            contact_person="Director",
            industry="Design"
        )

    def test_create_listing_rejects_zero_or_negative_positions(self):
        """Listing creation must reject total_positions < 1."""
        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        url = reverse('companies:create_listing')

        post_data = {
            'title': 'UI Intern',
            'category': self.category.id,
            'description': 'Valid description',
            'location_type': 'remote',
            'stipend': 5000,
            'total_positions': 0,
            'deadline': (date.today() + timedelta(days=14)).strftime('%Y-%m-%d'),
            'expected_duration': '3 months',
            'required_skills': [self.ui_skill.id],
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Positions must be at least 1")
        self.assertEqual(Internship.objects.filter(company=self.company_profile).count(), 0)

    def test_create_listing_rejects_past_or_today_deadline(self):
        """Listing creation must reject deadline <= today."""
        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        url = reverse('companies:create_listing')

        post_data = {
            'title': 'UI Intern',
            'category': self.category.id,
            'description': 'Valid description',
            'location_type': 'remote',
            'stipend': 5000,
            'total_positions': 2,
            'deadline': (date.today() - timedelta(days=1)).strftime('%Y-%m-%d'),
            'expected_duration': '3 months',
            'required_skills': [self.ui_skill.id],
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Deadline must be in the future")
        self.assertEqual(Internship.objects.filter(company=self.company_profile).count(), 0)

    def test_create_listing_rejects_negative_stipend(self):
        """Listing creation must reject negative stipend."""
        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        url = reverse('companies:create_listing')

        post_data = {
            'title': 'UI Intern',
            'category': self.category.id,
            'description': 'Valid description',
            'location_type': 'remote',
            'stipend': -1000,
            'total_positions': 2,
            'deadline': (date.today() + timedelta(days=14)).strftime('%Y-%m-%d'),
            'expected_duration': '3 months',
            'required_skills': [self.ui_skill.id],
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Stipend cannot be negative")
        self.assertEqual(Internship.objects.filter(company=self.company_profile).count(), 0)

    def test_model_clean_enforces_listing_validation(self):
        """Model-level clean() rejects invalid positions, deadline, and stipend."""
        # Positions < 1
        i1 = Internship(company=self.company_profile, title="T", category=self.category,
                        location_type="remote", deadline=date.today() + timedelta(days=5),
                        total_positions=0, expected_duration="3m")
        with self.assertRaises(ValidationError):
            i1.full_clean()

        # Deadline in the past
        i2 = Internship(company=self.company_profile, title="T", category=self.category,
                        location_type="remote", deadline=date.today() - timedelta(days=1),
                        total_positions=1, expected_duration="3m")
        with self.assertRaises(ValidationError):
            i2.full_clean()

        # Negative stipend
        i3 = Internship(company=self.company_profile, title="T", category=self.category,
                        location_type="remote", stipend=-500, deadline=date.today() + timedelta(days=5),
                        total_positions=1, expected_duration="3m")
        with self.assertRaises(ValidationError):
            i3.full_clean()

    def test_create_listing_accepts_valid_parameters(self):
        """Creating listing with future deadline, positive positions, and positive stipend succeeds."""
        self.client.login(email=self.company_user.email, password="DemoPassword123!")
        url = reverse('companies:create_listing')

        post_data = {
            'title': 'Valid UI Intern',
            'category': self.category.id,
            'description': 'Valid description',
            'location_type': 'remote',
            'stipend': 12000,
            'total_positions': 3,
            'deadline': (date.today() + timedelta(days=20)).strftime('%Y-%m-%d'),
            'expected_duration': '3 months',
            'required_skills': [self.ui_skill.id],
        }
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse('companies:dashboard'))
        self.assertEqual(Internship.objects.filter(company=self.company_profile, title='Valid UI Intern').count(), 1)




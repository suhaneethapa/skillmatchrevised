from datetime import date, timedelta
from decimal import Decimal

from django.contrib.messages import get_messages
from django.core.management import call_command
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import User, EmailVerificationToken
from core.models import Category, College, Skill
from companies.models import CompanyProfile, Internship, InternshipSkill
from students.models import StudentProfile, StudentSkill
from matching.engine import explain_match


class SeedDemoBrowseCommandTests(TestCase):
    """
    Tests for the seed_demo_browse management command:
    - Dataset creation and counts (8 companies, 32 approved listings, 4 pending, 3 students)
    - Ready-to-use demo account statuses (email_verified=True, status='active', suspended=False, college_verified=True)
    - Immediate workflow access for demo accounts without manual verification/approval
    - Strict protection of ordinary newly registered accounts (email verification & admin approval enforced)
    - Future deadlines on all approved listings
    - Required and preferred skills assignment
    - Idempotency (running multiple times produces 0 duplicates)
    - Isolation (non-demo records remain unaffected)
    - Browse isolation (pending listings excluded from approved browse results)
    - Student personalized matching diversity
    """

    def setUp(self):
        self.client = Client()

    def test_successful_demo_dataset_creation_and_counts(self):
        # 1. Execute command
        call_command("seed_demo_browse")

        # 2. Verify Companies
        demo_companies = User.objects.filter(
            email__endswith="@skillmatch.local",
            role="company"
        )
        self.assertEqual(demo_companies.count(), 8)

        for user in demo_companies:
            self.assertEqual(user.status, "active")
            self.assertTrue(user.is_active)
            self.assertTrue(user.email_verified)
            self.assertTrue(
                EmailVerificationToken.objects.filter(user=user, used=True).exists()
            )
            self.assertTrue(hasattr(user, "company_profile"))
            self.assertFalse(user.company_profile.suspended)
            self.assertTrue(user.company_profile.organization_name)
            self.assertTrue(user.company_profile.industry)
            self.assertTrue(user.company_profile.hq_location)
            # Verify password authentication works with demo credentials
            self.assertTrue(user.check_password("SkillMatchDemo2026!"))

        # 3. Verify Internships
        demo_internships = Internship.objects.filter(
            company__user__email__endswith="@skillmatch.local"
        )
        # 32 approved + 4 pending = 36 total
        self.assertEqual(demo_internships.count(), 36)

        approved_internships = demo_internships.filter(status="approved")
        self.assertEqual(approved_internships.count(), 32)

        pending_internships = demo_internships.filter(status="pending")
        self.assertEqual(pending_internships.count(), 4)

        # 4. Verify all approved internships have future deadlines
        today = date.today()
        for internship in approved_internships:
            self.assertGreater(
                internship.deadline,
                today,
                f"Internship '{internship.title}' deadline {internship.deadline} is not in the future."
            )
            self.assertGreaterEqual(internship.total_positions, 1)
            self.assertLessEqual(internship.total_positions, 5)
            self.assertTrue(internship.internship_skills.exists())

        # 5. Verify Student demonstration accounts
        demo_students = User.objects.filter(
            email__endswith="@skillmatch.local",
            role="student"
        )
        self.assertEqual(demo_students.count(), 3)

        for student_user in demo_students:
            self.assertEqual(student_user.status, "active")
            self.assertTrue(student_user.is_active)
            self.assertTrue(student_user.email_verified)
            self.assertTrue(
                EmailVerificationToken.objects.filter(user=student_user, used=True).exists()
            )
            self.assertTrue(hasattr(student_user, "student_profile"))
            self.assertTrue(student_user.student_profile.college_verified)
            self.assertTrue(student_user.student_profile.college.is_verified)
            self.assertEqual(student_user.student_profile.cv_file.name, "")
            self.assertTrue(student_user.student_skills.exists())
            self.assertTrue(student_user.check_password("SkillMatchDemo2026!"))

    def test_required_and_preferred_skills_distribution(self):
        call_command("seed_demo_browse")

        # Test specific technical listing: Python Django Developer Intern
        django_internship = Internship.objects.filter(
            title="Python Django Developer Intern"
        ).first()
        self.assertIsNotNone(django_internship)

        req_skills = set(
            django_internship.internship_skills.filter(is_required=True).values_list("skill__name", flat=True)
        )
        pref_skills = set(
            django_internship.internship_skills.filter(is_required=False).values_list("skill__name", flat=True)
        )

        self.assertEqual(req_skills, {"Python", "Django", "MySQL"})
        self.assertEqual(pref_skills, {"JavaScript", "React"})

        # Test design listing: UI/UX Design Intern
        uiux_internship = Internship.objects.filter(
            title="UI/UX Design Intern"
        ).first()
        self.assertIsNotNone(uiux_internship)

        uiux_req = set(
            uiux_internship.internship_skills.filter(is_required=True).values_list("skill__name", flat=True)
        )
        uiux_pref = set(
            uiux_internship.internship_skills.filter(is_required=False).values_list("skill__name", flat=True)
        )
        self.assertEqual(uiux_req, {"Figma", "UI/UX Design"})
        self.assertEqual(uiux_pref, {"Adobe Photoshop", "HTML", "CSS"})

    def test_idempotency_no_duplicates_on_repeated_execution(self):
        # Run 1
        call_command("seed_demo_browse")

        count_users_1 = User.objects.count()
        count_companies_1 = CompanyProfile.objects.count()
        count_internships_1 = Internship.objects.count()
        count_approved_1 = Internship.objects.filter(status="approved").count()
        count_pending_1 = Internship.objects.filter(status="pending").count()
        count_internship_skills_1 = InternshipSkill.objects.count()
        count_students_1 = StudentProfile.objects.count()
        count_student_skills_1 = StudentSkill.objects.count()

        # Run 2
        call_command("seed_demo_browse")

        count_users_2 = User.objects.count()
        count_companies_2 = CompanyProfile.objects.count()
        count_internships_2 = Internship.objects.count()
        count_approved_2 = Internship.objects.filter(status="approved").count()
        count_pending_2 = Internship.objects.filter(status="pending").count()
        count_internship_skills_2 = InternshipSkill.objects.count()
        count_students_2 = StudentProfile.objects.count()
        count_student_skills_2 = StudentSkill.objects.count()

        self.assertEqual(count_users_1, count_users_2)
        self.assertEqual(count_companies_1, count_companies_2)
        self.assertEqual(count_internships_1, count_internships_2)
        self.assertEqual(count_approved_1, count_approved_2)
        self.assertEqual(count_pending_1, count_pending_2)
        self.assertEqual(count_internship_skills_1, count_internship_skills_2)
        self.assertEqual(count_students_1, count_students_2)
        self.assertEqual(count_student_skills_1, count_student_skills_2)

    def test_non_demo_users_and_records_remain_unaffected(self):
        # Create pre-existing real records outside @skillmatch.local
        real_user = User.objects.create_user(
            email="real.company@example.com",
            password="OriginalPassword123!",
            role="company",
            status="pending_admin"
        )
        real_company = CompanyProfile.objects.create(
            user=real_user,
            organization_name="Real Organization Ltd.",
            contact_person="Hari Bahadur",
            industry="Telecommunications",
            hq_location="Lalitpur",
            suspended=True,
            suspension_reason="Under investigation",
        )
        real_category = Category.objects.create(name="Telecommunications Engineering")
        real_internship = Internship.objects.create(
            company=real_company,
            title="Telecom Network Intern",
            description="Pre-existing real internship listing",
            category=real_category,
            location_type="onsite",
            stipend=Decimal("20000.00"),
            deadline=date.today() + timedelta(days=90),
            total_positions=1,
            expected_duration="6 months",
            status="pending"
        )

        # Run demo seeder
        call_command("seed_demo_browse")

        # Reload pre-existing records and assert integrity
        real_user.refresh_from_db()
        real_company.refresh_from_db()
        real_internship.refresh_from_db()

        self.assertEqual(real_user.status, "pending_admin")
        self.assertTrue(real_user.check_password("OriginalPassword123!"))
        self.assertTrue(real_company.suspended)
        self.assertEqual(real_company.suspension_reason, "Under investigation")
        self.assertEqual(real_company.organization_name, "Real Organization Ltd.")
        self.assertEqual(real_internship.status, "pending")
        self.assertEqual(real_internship.description, "Pre-existing real internship listing")

    def test_pending_listings_not_appearing_in_approved_browse_results(self):
        call_command("seed_demo_browse")

        # Query public browse internships endpoint
        url = reverse("students:browse_internships")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        context_listings = response.context["listings"]
        context_titles = [item["internship"].title for item in context_listings]

        # 32 approved listings should be present
        approved_titles = list(
            Internship.objects.filter(
                company__user__email__endswith="@skillmatch.local",
                status="approved"
            ).values_list("title", flat=True)
        )
        self.assertEqual(len(approved_titles), 32)
        for title in approved_titles:
            self.assertIn(title, context_titles)

        # 4 pending listings must NOT be present
        pending_titles = list(
            Internship.objects.filter(
                company__user__email__endswith="@skillmatch.local",
                status="pending"
            ).values_list("title", flat=True)
        )
        self.assertEqual(len(pending_titles), 4)
        for title in pending_titles:
            self.assertNotIn(title, context_titles)

    def test_student_personalized_matching_variations(self):
        call_command("seed_demo_browse")

        student1 = User.objects.get(email="demo.student01@skillmatch.local")
        student2 = User.objects.get(email="demo.student02@skillmatch.local")
        student3 = User.objects.get(email="demo.student03@skillmatch.local")

        python_listing = Internship.objects.get(title="Python Django Developer Intern")
        data_listing = Internship.objects.get(title="Junior Data Analyst Intern")
        design_listing = Internship.objects.get(title="UI/UX Design Intern")

        # Student 1 (Web dev focus)
        match1_python = explain_match(student1, python_listing)
        match1_data = explain_match(student1, data_listing)
        match1_design = explain_match(student1, design_listing)

        self.assertGreaterEqual(match1_python["score"], 80.0)
        self.assertTrue(match1_python["eligible"])
        self.assertEqual(len(match1_python["gap"]), 0)

        # Student 2 (Data analytics focus)
        match2_data = explain_match(student2, data_listing)
        self.assertGreaterEqual(match2_data["score"], 70.0)
        self.assertTrue(match2_data["eligible"])
        self.assertIn("Python", match2_data["gap"])

        # Student 3 (Design focus)
        match3_design = explain_match(student3, design_listing)
        self.assertGreaterEqual(match3_design["score"], 70.0)
        self.assertTrue(match3_design["eligible"])
        self.assertEqual(len(match3_design["gap"]), 0)

        # Confirm different students have different match profiles
        self.assertNotEqual(match1_python["score"], match2_data["score"])
        self.assertNotEqual(match1_python["score"], match3_design["score"])

    def test_demo_accounts_can_immediately_access_intended_workflows(self):
        call_command("seed_demo_browse")

        # 1. Demo Company immediate workflow access
        company_login_success = self.client.login(
            email="demo.company01@skillmatch.local",
            password="SkillMatchDemo2026!"
        )
        self.assertTrue(company_login_success)

        resp = self.client.get(reverse("companies:dashboard"))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get(reverse("companies:my_listings"))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get(reverse("companies:create_listing"))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get(reverse("companies:profile"))
        self.assertEqual(resp.status_code, 200)

        self.client.logout()

        # 2. Demo Student immediate workflow access
        student_login_success = self.client.login(
            email="demo.student01@skillmatch.local",
            password="SkillMatchDemo2026!"
        )
        self.assertTrue(student_login_success)

        resp = self.client.get(reverse("students:dashboard"))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get(reverse("students:profile"))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get(reverse("students:skills_edit"))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get(reverse("students:my_applications"))
        # my_applications redirects to dashboard which is 200
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("students:dashboard"))

        self.client.logout()

    def test_ordinary_registered_accounts_remain_strictly_subject_to_verification_and_approval(self):
        call_command("seed_demo_browse")

        college = College.objects.first()
        listing = Internship.objects.filter(status="approved").first()

        # 1. Normal Student freshly registered (pending_email)
        normal_student = User.objects.create_user(
            email="normal.student@university.edu",
            password="NormalPassword123!",
            role="student",
            status="pending_email"
        )
        StudentProfile.objects.create(
            user=normal_student,
            college=college,
            department="Computer Science",
            semester=4,
            college_verified=False
        )

        self.assertFalse(normal_student.email_verified)

        # Logged in as pending_email student
        self.client.force_login(normal_student)

        # Blocked from dashboard by middleware -> redirected to account_status
        resp = self.client.get(reverse("students:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("accounts:account_status"))

        # Blocked from profile
        resp = self.client.get(reverse("students:profile"))
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("accounts:account_status"))

        # Blocked from applying -> redirected with error flash
        resp = self.client.post(
            reverse("students:apply_internship", args=[listing.id]),
            follow=True
        )
        self.assertRedirects(resp, reverse("students:internship_detail", args=[listing.id]))
        messages_text = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Please verify your email address" in m for m in messages_text))

        self.client.logout()

        # 2. Normal Student after email verification (pending_admin)
        normal_student.status = "pending_admin"
        normal_student.save()
        self.assertTrue(normal_student.email_verified)

        self.client.force_login(normal_student)

        # Blocked from dashboard -> redirected to account_status
        resp = self.client.get(reverse("students:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("accounts:account_status"))

        # Blocked from applying -> redirected with awaiting approval flash
        resp = self.client.post(
            reverse("students:apply_internship", args=[listing.id]),
            follow=True
        )
        self.assertRedirects(resp, reverse("students:internship_detail", args=[listing.id]))
        messages_text = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Your account is awaiting approval" in m for m in messages_text))

        self.client.logout()

        # 3. Normal Company freshly registered (pending_email)
        normal_company = User.objects.create_user(
            email="normal.company@business.com",
            password="NormalPassword123!",
            role="company",
            status="pending_email"
        )
        CompanyProfile.objects.create(
            user=normal_company,
            organization_name="Normal Commercial Corp",
            contact_person="Ramesh Shrestha",
            industry="Retail",
            hq_location="Kathmandu"
        )

        self.assertFalse(normal_company.email_verified)

        self.client.force_login(normal_company)

        # Blocked from company dashboard -> redirected to account_status
        resp = self.client.get(reverse("companies:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("accounts:account_status"))

        # Blocked from listings
        resp = self.client.get(reverse("companies:my_listings"))
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("accounts:account_status"))

        self.client.logout()

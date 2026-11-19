from django.test import TestCase
from matching.engine import compute_match_score, is_eligible, explain_match
from accounts.models import User
from core.models import College, Category, Skill
from companies.models import CompanyProfile, Internship, InternshipSkill
from students.models import StudentProfile, StudentSkill


class ExplainableMatchingEngineTests(TestCase):
    def test_100_percent_match(self):
        """Student with all required and preferred skills achieves 100% match."""
        student_skills = ['Python', 'Django', 'PostgreSQL']
        internship_skills = [
            ('Python', True),      # weight 2.0
            ('Django', True),      # weight 2.0
            ('PostgreSQL', False), # weight 1.0
        ]
        result = explain_match(student_skills, internship_skills)
        self.assertEqual(result['score'], 100.0)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['matched_required'], ['Python', 'Django'])
        self.assertEqual(result['missing_required'], [])
        self.assertEqual(result['matched_preferred'], ['PostgreSQL'])
        self.assertEqual(result['missing_preferred'], [])
        self.assertIn("100%", result['explanation'])
        self.assertIn("all required and preferred", result['explanation'].lower())

    def test_exactly_50_percent_match(self):
        """Student achieving exactly 50.0% is eligible (threshold is >= 50%)."""
        # Required weight: 2.0. Preferred weight: 1.0 + 1.0 = 2.0. Total = 4.0.
        # Student has 1 required skill (2.0/4.0 = 50.0%).
        student_skills = ['Python']
        internship_skills = [
            ('Python', True),      # 2.0 (matched)
            ('Docker', False),     # 1.0 (missing)
            ('Kubernetes', False), # 1.0 (missing)
        ]
        result = explain_match(student_skills, internship_skills)
        self.assertEqual(result['score'], 50.0)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['matched_required'], ['Python'])
        self.assertEqual(result['missing_required'], [])
        self.assertEqual(result['matched_preferred'], [])
        self.assertEqual(result['missing_preferred'], ['Docker', 'Kubernetes'])
        self.assertIn("Eligible (50.0%)", result['explanation'])

    def test_below_50_percent_match(self):
        """Student below 50.0% is marked not eligible with an explanation."""
        # Required: 2.0, 2.0, 2.0 (total = 6.0). Student has 1 = 2.0/6.0 = 33.33%.
        student_skills = ['Python']
        internship_skills = [
            ('Python', True),
            ('Django', True),
            ('PostgreSQL', True),
        ]
        result = explain_match(student_skills, internship_skills)
        self.assertEqual(result['score'], 33.33)
        self.assertFalse(result['eligible'])
        self.assertEqual(result['matched_required'], ['Python'])
        self.assertEqual(result['missing_required'], ['Django', 'PostgreSQL'])
        self.assertIn("Below 50% threshold (33.33%)", result['explanation'])
        self.assertIn("Missing required competencies: Django, PostgreSQL", result['explanation'])

    def test_missing_required_skills(self):
        """Missing required skills are listed accurately in the gap and missing_required fields."""
        student_skills = ['Git']
        internship_skills = [
            ('Python', True),
            ('Django', True),
            ('Git', False),
        ]
        result = explain_match(student_skills, internship_skills)
        self.assertEqual(result['score'], 20.0)  # 1.0 / (2.0 + 2.0 + 1.0) = 1/5 = 20%
        self.assertFalse(result['eligible'])
        self.assertEqual(result['missing_required'], ['Python', 'Django'])
        self.assertEqual(result['gap'], ['Python', 'Django'])
        self.assertEqual(result['matched_preferred'], ['Git'])

    def test_missing_preferred_skills(self):
        """Missing preferred skills do not block eligibility if required skills yield >= 50%."""
        student_skills = ['Python', 'Django']
        internship_skills = [
            ('Python', True),      # 2.0 (matched)
            ('Django', True),      # 2.0 (matched)
            ('AWS', False),        # 1.0 (missing)
        ]
        # Total = 5.0, matched = 4.0. Score = 80.0%.
        result = explain_match(student_skills, internship_skills)
        self.assertEqual(result['score'], 80.0)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['missing_required'], [])
        self.assertEqual(result['missing_preferred'], ['AWS'])
        self.assertIn("Eligible (80.0%)", result['explanation'])

    def test_student_with_no_skills(self):
        """Student with zero skills receives 0.0% score and ineligible explanation."""
        student_skills = []
        internship_skills = [
            ('Python', True),
            ('Django', False),
        ]
        result = explain_match(student_skills, internship_skills)
        self.assertEqual(result['score'], 0.0)
        self.assertFalse(result['eligible'])
        self.assertEqual(result['matched_required'], [])
        self.assertEqual(result['missing_required'], ['Python'])
        self.assertEqual(result['matched_preferred'], [])
        self.assertEqual(result['missing_preferred'], ['Django'])
        self.assertIn("Below 50% threshold (0.0%)", result['explanation'])

    def test_match_explanation_agrees_with_existing_score(self):
        """explain_match score exactly equals compute_match_score across multiple test cases."""
        test_cases = [
            (['A', 'B'], [('A', True), ('B', True)]),
            (['A'], [('A', True), ('B', False)]),
            (['B'], [('A', True), ('B', False)]),
            ([], [('A', True)]),
            (['A', 'C'], [('A', True), ('B', True), ('C', False), ('D', False)]),
        ]
        for student_skills, req_tuples in test_cases:
            canonical_score, canonical_gap = compute_match_score(student_skills, req_tuples)
            explanation = explain_match(student_skills, req_tuples)
            self.assertEqual(explanation['score'], canonical_score)
            self.assertEqual(explanation['gap'], canonical_gap)
            self.assertEqual(explanation['eligible'], is_eligible(canonical_score))

    def test_explain_match_with_orm_models(self):
        """explain_match works seamlessly when passed User and Internship model instances."""
        college = College.objects.create(name="Apex College")
        category = Category.objects.create(name="Engineering")
        py_skill = Skill.objects.create(name="Python", category=category)
        dj_skill = Skill.objects.create(name="Django", category=category)
        aws_skill = Skill.objects.create(name="AWS", category=category)

        student = User.objects.create_user(
            email="orm_student@example.com",
            password="Password123!",
            role="student",
            status="active"
        )
        StudentProfile.objects.create(
            user=student,
            college=college,
            department="BIM",
            semester=6,
            college_verified=True
        )
        StudentSkill.objects.create(student=student, skill=py_skill)
        StudentSkill.objects.create(student=student, skill=dj_skill)

        company_user = User.objects.create_user(
            email="orm_company@example.com",
            password="Password123!",
            role="company",
            status="active"
        )
        company_profile = CompanyProfile.objects.create(
            user=company_user,
            organization_name="ORM Corp",
            contact_person="Lead",
            industry="IT",
            hq_location="Kathmandu"
        )
        from datetime import date, timedelta
        internship = Internship.objects.create(
            company=company_profile,
            title="Fullstack Python Intern",
            category=category,
            location_type="remote",
            deadline=date.today() + timedelta(days=20),
            total_positions=2,
            expected_duration="3 months",
            status="approved"
        )
        InternshipSkill.objects.create(internship=internship, skill=py_skill, is_required=True)
        InternshipSkill.objects.create(internship=internship, skill=dj_skill, is_required=True)
        InternshipSkill.objects.create(internship=internship, skill=aws_skill, is_required=False)

        result = explain_match(student, internship)
        # Required = 2.0 + 2.0 = 4.0; Preferred = 1.0; Total = 5.0. Matched = 4.0 -> 80.0%
        self.assertEqual(result['score'], 80.0)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['matched_required'], ['Python', 'Django'])
        self.assertEqual(result['missing_preferred'], ['AWS'])

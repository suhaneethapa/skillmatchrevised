"""
seed_demo management command
============================
Loads a small, clearly-labelled DEMO dataset into an empty SkillMatch database
so the system can be demonstrated to supervisors without registering
everything by hand.

All data created here is fictional demo content for academic presentation.
Run with:  python manage.py seed_demo
Remove it all with:  python manage.py flush   (then re-run migrate if needed)
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from core.models import College, Category, Skill
from matching.engine import compute_match_score
from students.models import StudentProfile, StudentSkill, Application
from companies.models import CompanyProfile, Internship, InternshipSkill


DEMO_PASSWORD = "Demo1234!"

COLLEGES = ["Prime College", "St. Xavier's College", "Kathmandu College of Management"]

CATEGORIES = {
    "Programming Languages": ["Python", "Java", "JavaScript", "PHP", "C++"],
    "Web Frameworks": ["Django", "React", "Laravel", "Node.js"],
    "Databases": ["MySQL", "PostgreSQL", "MongoDB"],
    "Design": ["Figma", "Adobe Photoshop", "UI/UX Design"],
    "Data & Analytics": ["Excel", "SQL", "Power BI"],
}

# (title, category, location, stipend, positions, duration, status, days_to_deadline,
#  [required skill names], [preferred skill names])
INTERNSHIPS = [
    (
        "Python Web Development Intern",
        "Programming Languages",
        "hybrid",
        15000,
        2,
        "3 months",
        "approved",
        20,
        ["Python", "Django", "MySQL"],
        ["JavaScript", "React"],
    ),
    (
        "Frontend Development Intern",
        "Web Frameworks",
        "onsite",
        10000,
        1,
        "2 months",
        "approved",
        12,
        ["JavaScript", "React"],
        ["Figma"],
    ),
    (
        "Data Analysis Intern",
        "Data & Analytics",
        "remote",
        None,
        3,
        "2 months",
        "approved",
        -5,  # expired deadline, shows the "Closed" state
        ["Excel", "SQL"],
        ["Power BI", "Python"],
    ),
    (
        "UI/UX Design Intern",
        "Design",
        "onsite",
        12000,
        1,
        "3 months",
        "pending",
        30,
        ["Figma", "UI/UX Design"],
        ["Adobe Photoshop"],
    ),
]

STUDENTS = [
    # (email, college, department, semester, [skill names])
    (
        "student@demo.local",
        "Prime College",
        "BIM",
        6,
        ["Python", "Django", "JavaScript", "MySQL", "React"],
    ),
    (
        "student2@demo.local",
        "St. Xavier's College",
        "BIM",
        5,
        ["JavaScript", "React", "Figma"],
    ),
]

# Which demo students apply to which demo internship (by index), and the status.
APPLICATIONS = [
    (0, 0, "pending"),   # student@demo.local -> Python Web Development Intern
    (1, 0, "pending"),   # student2@demo.local -> Python Web Development Intern
    (0, 2, "pending"),   # expired listing -> shows "Closed" state
]


class Command(BaseCommand):
    help = "Load clearly-labelled DEMO data for academic presentations. All fictional."

    @transaction.atomic
    def handle(self, *args, **options):
        if User.objects.exists():
            self.stderr.write(
                self.style.ERROR(
                    "Database is not empty. seed_demo only runs on an empty "
                    "database. Use 'python manage.py flush' first if you really "
                    "want to start over."
                )
            )
            return

        self.stdout.write("Creating DEMO dataset (fictional, for demonstration)...")

        # ── Master data ──────────────────────────────────────────────
        colleges = {name: College.objects.create(name=name) for name in COLLEGES}

        skills = {}
        for cat_name, skill_names in CATEGORIES.items():
            category = Category.objects.create(name=cat_name)
            for skill_name in skill_names:
                skills[skill_name] = Skill.objects.create(
                    name=skill_name, category=category
                )

        # ── Admin ────────────────────────────────────────────────────
        User.objects.create_superuser(
            "admin@demo.local", DEMO_PASSWORD, role="admin", status="active"
        )

        # ── Demo company ─────────────────────────────────────────────
        company_user = User.objects.create_user(
            "company@demo.local", DEMO_PASSWORD, role="company", status="active"
        )
        company = CompanyProfile.objects.create(
            user=company_user,
            organization_name="Himal Tech Labs Pvt. Ltd.",
            contact_person="Anish Karki",
            industry="Software Development",
            description=(
                "A small Kathmandu-based software company building web "
                "applications for local businesses. (Demo organization)"
            ),
            website_url="https://example.com",
            hq_location="Kathmandu",
        )

        # ── Demo internships ─────────────────────────────────────────
        internship_objs = []
        for (
            title,
            cat_name,
            location,
            stipend,
            positions,
            duration,
            status,
            days_to_deadline,
            required,
            preferred,
        ) in INTERNSHIPS:
            internship = Internship.objects.create(
                company=company,
                title=title,
                description=f"{title} at {company.organization_name}. (Demo listing)",
                category=Category.objects.get(name=cat_name),
                location_type=location,
                stipend=stipend,
                deadline=date.today() + timedelta(days=days_to_deadline),
                total_positions=positions,
                expected_duration=duration,
                status=status,
            )
            for name in required:
                InternshipSkill.objects.create(
                    internship=internship, skill=skills[name], is_required=True
                )
            for name in preferred:
                InternshipSkill.objects.create(
                    internship=internship, skill=skills[name], is_required=False
                )
            internship_objs.append(internship)

        # ── Demo students ────────────────────────────────────────────
        student_users = []
        for email, college_name, department, semester, skill_names in STUDENTS:
            user = User.objects.create_user(
                email, DEMO_PASSWORD, role="student", status="active"
            )
            StudentProfile.objects.create(
                user=user,
                college=colleges[college_name],
                department=department,
                semester=semester,
                bio="Demo student account for academic presentation.",
            )
            for name in skill_names:
                StudentSkill.objects.create(student=user, skill=skills[name])
            student_users.append(user)

        # ── Demo applications (real match scores from the engine) ────
        for student_idx, internship_idx, status in APPLICATIONS:
            student = student_users[student_idx]
            internship = internship_objs[internship_idx]
            student_skill_names = list(
                student.student_skills.values_list("skill__name", flat=True)
            )
            internship_skills = list(
                internship.internship_skills.values_list("skill__name", "is_required")
            )
            score, _ = compute_match_score(student_skill_names, internship_skills)
            Application.objects.create(
                student=student,
                internship=internship,
                status=status,
                match_score=score,
            )

        self.stdout.write(self.style.SUCCESS("Demo data loaded."))
        self.stdout.write("")
        self.stdout.write("Login credentials (all demo accounts):")
        self.stdout.write(f"  Admin:    admin@demo.local / {DEMO_PASSWORD}")
        self.stdout.write(f"  Company:  company@demo.local / {DEMO_PASSWORD}")
        self.stdout.write(f"  Students: student@demo.local, student2@demo.local / {DEMO_PASSWORD}")
        self.stdout.write("")
        self.stdout.write("Everything above is FICTIONAL demo content for the")
        self.stdout.write("academic presentation. Remove it with: python manage.py flush")

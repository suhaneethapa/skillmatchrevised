"""
seed_demo_browse management command
===================================
Populates a comprehensive, realistic DEMO dataset for academic supervisor
demonstration of internship browsing, skill-based matching, and moderation.

Features:
- 8 fictional Nepalese companies across tech, design, data, finance, tourism, NGO.
- 32 approved internship listings with future deadlines, realistic stipends/unpaid,
  and rich required/preferred skill distributions.
- 4 separate pending listings for administrator moderation demonstrations.
- 3 student demonstration accounts with distinct skill profiles demonstrating
  personalized matching scores and gap analysis.
- Completely safe and idempotent: uses transactions and update_or_create logic;
  safe to execute repeatedly without duplicating data or corrupting existing records.
- Strictly operates within the reserved demo namespace (@skillmatch.local).

Usage:
    python manage.py seed_demo_browse
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User, EmailVerificationToken
from core.models import Category, College, Skill
from companies.models import CompanyProfile, Internship, InternshipSkill
from students.models import StudentProfile, StudentSkill


DEMO_PASSWORD = "SkillMatchDemo2026!"
DEMO_EMAIL_DOMAIN = "@skillmatch.local"

# ── Categories & Skills Setup ──────────────────────────────────────────────
CATEGORIES_AND_SKILLS = {
    "Software and Web Development": [
        "Python", "Django", "JavaScript", "React", "PHP", "HTML", "CSS"
    ],
    "Data Analytics": [
        "Excel", "SQL", "Power BI", "MySQL"
    ],
    "UI/UX and Graphic Design": [
        "Figma", "UI/UX Design", "Adobe Photoshop"
    ],
    "Digital Marketing": [
        "Digital Marketing", "SEO", "Content Writing", "Social Media"
    ],
    "Finance and Accounting": [
        "Financial Analysis", "Accounting"
    ],
    "Business Administration": [
        "Business Research", "Communication", "Project Management"
    ],
    "Education": [
        "Lesson Planning"
    ],
    "Hospitality and Tourism": [
        "Hospitality Management", "Customer Service"
    ],
    "Healthcare Administration": [
        "Health Records Management"
    ],
    "NGO and Social Impact": [
        "Community Outreach"
    ],
}

# ── Fictional Companies ───────────────────────────────────────────────────
COMPANIES = [
    {
        "email": "demo.company01@skillmatch.local",
        "name": "Kathmandu Codeworks",
        "contact_person": "Prashant Adhikari",
        "industry": "Software Development",
        "hq_location": "Kathmandu, Bagmati",
        "website_url": "https://kathmanducodeworks.example.com",
        "description": (
            "Kathmandu Codeworks is a software engineering company based in Kathmandu "
            "specializing in enterprise web applications, cloud architecture, and open-source systems. "
            "(Demonstration organization for academic supervisor review)"
        ),
    },
    {
        "email": "demo.company02@skillmatch.local",
        "name": "Lalitpur Digital Studio",
        "contact_person": "Rojina Shakya",
        "industry": "Design and Creative Services",
        "hq_location": "Lalitpur, Bagmati",
        "website_url": "https://lalitpurstudio.example.com",
        "description": (
            "Lalitpur Digital Studio is a creative design agency located in Patan, Lalitpur, "
            "focused on human-centered UI/UX design, brand identity systems, and digital product prototyping. "
            "(Demonstration organization for academic supervisor review)"
        ),
    },
    {
        "email": "demo.company03@skillmatch.local",
        "name": "Valley Data Solutions",
        "contact_person": "Bikash Shrestha",
        "industry": "Data Analytics",
        "hq_location": "Kathmandu, Bagmati",
        "website_url": "https://valleydatasolutions.example.com",
        "description": (
            "Valley Data Solutions provides business intelligence, automated analytics pipelines, "
            "and data reporting infrastructure for growing organizations across Nepal. "
            "(Demonstration organization for academic supervisor review)"
        ),
    },
    {
        "email": "demo.company04@skillmatch.local",
        "name": "CloudPeak Nepal",
        "contact_person": "Anil Maharjan",
        "industry": "IT Services",
        "hq_location": "Bhaktapur, Bagmati",
        "website_url": "https://cloudpeaknepal.example.com",
        "description": (
            "CloudPeak Nepal delivers managed IT solutions, secure networking, systems integration, "
            "and technical infrastructure support for institutions and enterprises. "
            "(Demonstration organization for academic supervisor review)"
        ),
    },
    {
        "email": "demo.company05@skillmatch.local",
        "name": "GreenPath Social Impact",
        "contact_person": "Sunita Thapa",
        "industry": "NGO and Development",
        "hq_location": "Kathmandu, Bagmati",
        "website_url": "https://greenpathimpact.example.com",
        "description": (
            "GreenPath Social Impact is a non-governmental initiative dedicated to environmental sustainability, "
            "community resilience, and youth empowerment in urban and rural Nepal. "
            "(Demonstration organization for academic supervisor review)"
        ),
    },
    {
        "email": "demo.company06@skillmatch.local",
        "name": "Summit Creative House",
        "contact_person": "Suman Karki",
        "industry": "Marketing and Communications",
        "hq_location": "Lalitpur, Bagmati",
        "website_url": "https://summitcreative.example.com",
        "description": (
            "Summit Creative House is a dynamic digital marketing agency crafting data-driven outreach, "
            "brand storytelling, and high-impact omnichannel media campaigns. "
            "(Demonstration organization for academic supervisor review)"
        ),
    },
    {
        "email": "demo.company07@skillmatch.local",
        "name": "Terai Business Analytics",
        "contact_person": "Deepak Chaudhary",
        "industry": "Business and Finance",
        "hq_location": "Butwal, Lumbini",
        "website_url": "https://teraianalytics.example.com",
        "description": (
            "Terai Business Analytics specializes in financial modeling, agricultural supply-chain intelligence, "
            "and SME growth advisory across the southern commercial corridors. "
            "(Demonstration organization for academic supervisor review)"
        ),
    },
    {
        "email": "demo.company08@skillmatch.local",
        "name": "Pokhara Hospitality Labs",
        "contact_person": "Kabita Gurung",
        "industry": "Hospitality and Tourism",
        "hq_location": "Pokhara, Gandaki",
        "website_url": "https://pokharahospitality.example.com",
        "description": (
            "Pokhara Hospitality Labs explores modern guest experience workflows, sustainable ecotourism research, "
            "and digital management tools for the Himalayan hospitality sector. "
            "(Demonstration organization for academic supervisor review)"
        ),
    },
]

# ── 32 Approved Listings (4 per Company) ──────────────────────────────────
APPROVED_INTERNSHIPS = [
    # Company 1: Kathmandu Codeworks
    {
        "company_email": "demo.company01@skillmatch.local",
        "title": "Python Django Developer Intern",
        "category": "Software and Web Development",
        "location_type": "hybrid",
        "stipend": Decimal("18000.00"),
        "days_to_deadline": 35,
        "total_positions": 2,
        "expected_duration": "3 months",
        "required_skills": ["Python", "Django", "MySQL"],
        "preferred_skills": ["JavaScript", "React"],
        "description": (
            "Join our backend engineering squad to develop scalable RESTful APIs and database schemas "
            "for enterprise client services. You will participate in agile sprint ceremonies, write unit tests, "
            "and optimize query performance. (Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company01@skillmatch.local",
        "title": "Frontend React Developer Intern",
        "category": "Software and Web Development",
        "location_type": "onsite",
        "stipend": Decimal("16000.00"),
        "days_to_deadline": 40,
        "total_positions": 2,
        "expected_duration": "3 months",
        "required_skills": ["JavaScript", "React", "HTML", "CSS"],
        "preferred_skills": ["Figma", "UI/UX Design"],
        "description": (
            "Collaborate with our product designers and full-stack engineers to build modular, accessible "
            "user interfaces. You will translate wireframes into clean React components and integrate client-side "
            "state management. (Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company01@skillmatch.local",
        "title": "Full Stack Web Intern (PHP & MySQL)",
        "category": "Software and Web Development",
        "location_type": "remote",
        "stipend": Decimal("15000.00"),
        "days_to_deadline": 45,
        "total_positions": 1,
        "expected_duration": "4 months",
        "required_skills": ["PHP", "MySQL", "HTML", "CSS"],
        "preferred_skills": ["JavaScript", "Communication"],
        "description": (
            "Assist in maintaining and expanding client web applications built on PHP and relational databases. "
            "Focus on form handling, secure authentication workflows, schema indexing, and responsive page styling. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company01@skillmatch.local",
        "title": "Cloud Systems & DevOps Intern",
        "category": "Software and Web Development",
        "location_type": "hybrid",
        "stipend": None,  # Unpaid learning internship
        "days_to_deadline": 30,
        "total_positions": 1,
        "expected_duration": "3 months",
        "required_skills": ["Python", "SQL"],
        "preferred_skills": ["Project Management", "Communication"],
        "description": (
            "Gain structured exposure to CI/CD pipelines, container configurations, and infrastructure monitoring "
            "under senior cloud architects. Includes hands-on cloud certification preparation. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },

    # Company 2: Lalitpur Digital Studio
    {
        "company_email": "demo.company02@skillmatch.local",
        "title": "UI/UX Design Intern",
        "category": "UI/UX and Graphic Design",
        "location_type": "onsite",
        "stipend": Decimal("15000.00"),
        "days_to_deadline": 30,
        "total_positions": 2,
        "expected_duration": "3 months",
        "required_skills": ["Figma", "UI/UX Design"],
        "preferred_skills": ["Adobe Photoshop", "HTML", "CSS"],
        "description": (
            "Design user journeys, wireframes, and interactive clickable prototypes for mobile and web apps. "
            "Participate in user research interviews, usability testing, and design critique reviews. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company02@skillmatch.local",
        "title": "Digital Graphic Design Intern",
        "category": "UI/UX and Graphic Design",
        "location_type": "onsite",
        "stipend": Decimal("14000.00"),
        "days_to_deadline": 25,
        "total_positions": 1,
        "expected_duration": "2 months",
        "required_skills": ["Adobe Photoshop", "Figma"],
        "preferred_skills": ["UI/UX Design", "Content Writing"],
        "description": (
            "Create digital marketing collateral, social media assets, vector illustrations, and presentation layouts "
            "for creative sector clients while upholding strict brand guidelines. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company02@skillmatch.local",
        "title": "Design Systems & Prototyping Intern",
        "category": "UI/UX and Graphic Design",
        "location_type": "hybrid",
        "stipend": Decimal("16000.00"),
        "days_to_deadline": 50,
        "total_positions": 1,
        "expected_duration": "3 months",
        "required_skills": ["Figma", "UI/UX Design", "CSS"],
        "preferred_skills": ["JavaScript", "React"],
        "description": (
            "Help construct and maintain design token libraries and component states in Figma to bridge the gap "
            "between visual design and frontend implementation. (Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company02@skillmatch.local",
        "title": "Creative Visual Storytelling Intern",
        "category": "UI/UX and Graphic Design",
        "location_type": "remote",
        "stipend": None,  # Unpaid academic internship
        "days_to_deadline": 35,
        "total_positions": 2,
        "expected_duration": "2 months",
        "required_skills": ["Adobe Photoshop", "Content Writing"],
        "preferred_skills": ["Communication", "Digital Marketing"],
        "description": (
            "Develop narrative mood boards, visual storyboards, and multi-channel creative storytelling campaigns "
            "for cultural exhibitions and community storytelling projects. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },

    # Company 3: Valley Data Solutions
    {
        "company_email": "demo.company03@skillmatch.local",
        "title": "Junior Data Analyst Intern",
        "category": "Data Analytics",
        "location_type": "hybrid",
        "stipend": Decimal("18000.00"),
        "days_to_deadline": 40,
        "total_positions": 2,
        "expected_duration": "4 months",
        "required_skills": ["SQL", "Excel", "Python"],
        "preferred_skills": ["Power BI", "Financial Analysis"],
        "description": (
            "Extract, clean, and validate business data from relational databases. Perform exploratory data analysis, "
            "track KPI anomalies, and prepare monthly summary presentations for client decision-makers. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company03@skillmatch.local",
        "title": "Business Intelligence & Power BI Intern",
        "category": "Data Analytics",
        "location_type": "onsite",
        "stipend": Decimal("17000.00"),
        "days_to_deadline": 35,
        "total_positions": 1,
        "expected_duration": "3 months",
        "required_skills": ["Power BI", "SQL", "Excel"],
        "preferred_skills": ["Business Research", "Communication"],
        "description": (
            "Build interactive reports and dashboards, write optimized DAX calculations, and automate scheduled "
            "data refreshes to deliver intuitive metrics to regional commercial clients. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company03@skillmatch.local",
        "title": "Database Operations & ETL Intern",
        "category": "Data Analytics",
        "location_type": "hybrid",
        "stipend": Decimal("16000.00"),
        "days_to_deadline": 45,
        "total_positions": 2,
        "expected_duration": "3 months",
        "required_skills": ["MySQL", "SQL", "Python"],
        "preferred_skills": ["Excel", "Project Management"],
        "description": (
            "Support daily database operations, write automated Python ETL ingestion scripts, and monitor database "
            "indexing to ensure reliable analytics pipeline performance. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company03@skillmatch.local",
        "title": "Quantitative Research Intern",
        "category": "Data Analytics",
        "location_type": "remote",
        "stipend": Decimal("15000.00"),
        "days_to_deadline": 60,
        "total_positions": 1,
        "expected_duration": "3 months",
        "required_skills": ["Excel", "Business Research", "SQL"],
        "preferred_skills": ["Python", "Communication"],
        "description": (
            "Conduct structured data analysis on economic indicators, synthesize survey datasets, and produce "
            "concise analytical research notes under the supervision of senior researchers. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },

    # Company 4: CloudPeak Nepal
    {
        "company_email": "demo.company04@skillmatch.local",
        "title": "IT Systems Support Intern",
        "category": "Software and Web Development",
        "location_type": "onsite",
        "stipend": Decimal("12000.00"),
        "days_to_deadline": 30,
        "total_positions": 2,
        "expected_duration": "3 months",
        "required_skills": ["Communication", "Project Management"],
        "preferred_skills": ["Python", "MySQL"],
        "description": (
            "Assist IT engineers in network troubleshooting, workstation setups, security access reviews, "
            "and technical support ticket resolution for corporate clients in Bhaktapur. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company04@skillmatch.local",
        "title": "Database Administration Support Intern",
        "category": "Data Analytics",
        "location_type": "hybrid",
        "stipend": Decimal("15000.00"),
        "days_to_deadline": 45,
        "total_positions": 1,
        "expected_duration": "4 months",
        "required_skills": ["MySQL", "SQL"],
        "preferred_skills": ["Python", "Project Management"],
        "description": (
            "Assist database administrators with backup verification routines, query execution profiling, "
            "and user permissions management across client MySQL server clusters. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company04@skillmatch.local",
        "title": "Enterprise Web Portal Intern",
        "category": "Software and Web Development",
        "location_type": "remote",
        "stipend": Decimal("16000.00"),
        "days_to_deadline": 50,
        "total_positions": 2,
        "expected_duration": "3 months",
        "required_skills": ["Python", "Django", "HTML", "CSS"],
        "preferred_skills": ["JavaScript", "MySQL"],
        "description": (
            "Develop internal staff portals and management dashboards utilizing Django's built-in authentication, "
            "role permissioning, and templating framework. (Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company04@skillmatch.local",
        "title": "Technical Documentation & Training Intern",
        "category": "Education",
        "location_type": "onsite",
        "stipend": None,  # Unpaid academic training internship
        "days_to_deadline": 35,
        "total_positions": 1,
        "expected_duration": "2 months",
        "required_skills": ["Communication", "Project Management"],
        "preferred_skills": ["Content Writing", "Lesson Planning"],
        "description": (
            "Draft clear user manuals, troubleshooting guides, and slide materials for institutional IT workshops "
            "and vocational technology training programs. (Demonstration listing for academic supervisor review)"
        ),
    },

    # Company 5: GreenPath Social Impact
    {
        "company_email": "demo.company05@skillmatch.local",
        "title": "Community Development Intern",
        "category": "NGO and Social Impact",
        "location_type": "onsite",
        "stipend": Decimal("12000.00"),
        "days_to_deadline": 45,
        "total_positions": 3,
        "expected_duration": "4 months",
        "required_skills": ["Communication", "Community Outreach"],
        "preferred_skills": ["Project Management", "Content Writing"],
        "description": (
            "Coordinate grassroots community workshops, organize volunteer fieldwork schedules, and assist in "
            "collecting monitoring and evaluation data across peri-urban youth development initiatives. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company05@skillmatch.local",
        "title": "Environmental Project Coordinator Intern",
        "category": "NGO and Social Impact",
        "location_type": "hybrid",
        "stipend": Decimal("14000.00"),
        "days_to_deadline": 40,
        "total_positions": 2,
        "expected_duration": "3 months",
        "required_skills": ["Project Management", "Communication"],
        "preferred_skills": ["Excel", "Community Outreach"],
        "description": (
            "Track project deliverables for urban forestry and waste-reduction grants. Prepare milestone checklists, "
            "schedule stakeholder consultations, and compile quarterly progress updates. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company05@skillmatch.local",
        "title": "Nonprofit Communications & Grants Intern",
        "category": "NGO and Social Impact",
        "location_type": "remote",
        "stipend": Decimal("13000.00"),
        "days_to_deadline": 50,
        "total_positions": 1,
        "expected_duration": "3 months",
        "required_skills": ["Content Writing", "Communication"],
        "preferred_skills": ["Digital Marketing", "Project Management"],
        "description": (
            "Draft inspiring impact stories, quarterly supporter newsletters, and preliminary grant proposals "
            "advancing community-led sustainability and education projects in Nepal. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company05@skillmatch.local",
        "title": "Social Impact Field Research Intern",
        "category": "Business Administration",
        "location_type": "onsite",
        "stipend": None,  # Unpaid research placement with travel stipends
        "days_to_deadline": 30,
        "total_positions": 2,
        "expected_duration": "2 months",
        "required_skills": ["Business Research", "Communication"],
        "preferred_skills": ["Excel", "Community Outreach"],
        "description": (
            "Conduct structured household surveys and focus group interviews in Chitwan to evaluate baseline "
            "community socioeconomic indicators and rural livelihood initiatives. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },

    # Company 6: Summit Creative House
    {
        "company_email": "demo.company06@skillmatch.local",
        "title": "Digital Marketing Intern",
        "category": "Digital Marketing",
        "location_type": "hybrid",
        "stipend": Decimal("15000.00"),
        "days_to_deadline": 35,
        "total_positions": 2,
        "expected_duration": "3 months",
        "required_skills": ["Digital Marketing", "SEO", "Social Media"],
        "preferred_skills": ["Content Writing", "Adobe Photoshop"],
        "description": (
            "Manage client social media accounts, assist with Google Ads and Meta campaign monitoring, "
            "and compile weekly audience engagement and conversion analytics reports. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company06@skillmatch.local",
        "title": "Content Writing & SEO Intern",
        "category": "Digital Marketing",
        "location_type": "remote",
        "stipend": Decimal("14000.00"),
        "days_to_deadline": 40,
        "total_positions": 2,
        "expected_duration": "3 months",
        "required_skills": ["Content Writing", "SEO"],
        "preferred_skills": ["Communication", "Digital Marketing"],
        "description": (
            "Research industry developments and write well-structured, SEO-optimized blog articles and website copy "
            "to enhance organic search visibility for digital brands. (Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company06@skillmatch.local",
        "title": "Brand Strategy & Campaign Intern",
        "category": "Digital Marketing",
        "location_type": "onsite",
        "stipend": Decimal("16000.00"),
        "days_to_deadline": 45,
        "total_positions": 1,
        "expected_duration": "4 months",
        "required_skills": ["Digital Marketing", "Communication"],
        "preferred_skills": ["Figma", "Business Research"],
        "description": (
            "Support brand strategists in consumer market research, creative campaign conceptualization, "
            "and presentation pitch deck creation for FMCG and lifestyle clients. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company06@skillmatch.local",
        "title": "Social Media & Influencer Outreach Intern",
        "category": "Digital Marketing",
        "location_type": "hybrid",
        "stipend": None,  # Unpaid portfolio internship
        "days_to_deadline": 30,
        "total_positions": 1,
        "expected_duration": "2 months",
        "required_skills": ["Communication", "Digital Marketing"],
        "preferred_skills": ["Adobe Photoshop", "Content Writing"],
        "description": (
            "Coordinate outreach with digital content creators, track campaign deliverables, and curate interactive "
            "social media stories for youth-oriented product launches. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },

    # Company 7: Terai Business Analytics
    {
        "company_email": "demo.company07@skillmatch.local",
        "title": "Financial Operations Intern",
        "category": "Finance and Accounting",
        "location_type": "onsite",
        "stipend": Decimal("15000.00"),
        "days_to_deadline": 45,
        "total_positions": 2,
        "expected_duration": "3 months",
        "required_skills": ["Accounting", "Excel", "Financial Analysis"],
        "preferred_skills": ["SQL", "Communication"],
        "description": (
            "Assist the accounting team in daily ledger reconciliation, invoice audits, accounts payable schedules, "
            "and monthly financial variance summaries in Butwal. (Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company07@skillmatch.local",
        "title": "Corporate Financial Analyst Intern",
        "category": "Finance and Accounting",
        "location_type": "hybrid",
        "stipend": Decimal("17000.00"),
        "days_to_deadline": 50,
        "total_positions": 1,
        "expected_duration": "4 months",
        "required_skills": ["Financial Analysis", "Excel"],
        "preferred_skills": ["Power BI", "Business Research"],
        "description": (
            "Work alongside financial consultants to construct dynamic cash flow projection models, assess capital "
            "expenditure proposals, and prepare executive briefing decks. (Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company07@skillmatch.local",
        "title": "Business Research & Market Expansion Intern",
        "category": "Business Administration",
        "location_type": "remote",
        "stipend": Decimal("14000.00"),
        "days_to_deadline": 35,
        "total_positions": 2,
        "expected_duration": "3 months",
        "required_skills": ["Business Research", "Excel", "Communication"],
        "preferred_skills": ["Project Management", "Financial Analysis"],
        "description": (
            "Investigate regional trade statistics, profile emerging commercial competitors, and synthesize market "
            "entry feasibility assessments for agribusiness and retail expansion. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company07@skillmatch.local",
        "title": "SME Credit Assessment Intern",
        "category": "Finance and Accounting",
        "location_type": "onsite",
        "stipend": None,  # Unpaid credit advisory placement
        "days_to_deadline": 40,
        "total_positions": 1,
        "expected_duration": "3 months",
        "required_skills": ["Accounting", "Financial Analysis"],
        "preferred_skills": ["Excel", "Communication"],
        "description": (
            "Assist credit officers in evaluating business balance sheets, debt service ratios, and collateral "
            "documentation for small business development loan reviews. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },

    # Company 8: Pokhara Hospitality Labs
    {
        "company_email": "demo.company08@skillmatch.local",
        "title": "Hospitality Operations Intern",
        "category": "Hospitality and Tourism",
        "location_type": "onsite",
        "stipend": Decimal("16000.00"),
        "days_to_deadline": 45,
        "total_positions": 3,
        "expected_duration": "4 months",
        "required_skills": ["Hospitality Management", "Customer Service", "Communication"],
        "preferred_skills": ["Project Management"],
        "description": (
            "Gain immersive practical experience across front-desk reservation management, concierge coordination, "
            "and guest feedback systems in premier lakeside resort partner properties in Pokhara. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company08@skillmatch.local",
        "title": "Sustainable Tourism Research Intern",
        "category": "Hospitality and Tourism",
        "location_type": "hybrid",
        "stipend": Decimal("15000.00"),
        "days_to_deadline": 40,
        "total_positions": 2,
        "expected_duration": "3 months",
        "required_skills": ["Business Research", "Communication"],
        "preferred_skills": ["Hospitality Management", "Excel"],
        "description": (
            "Collect and analyze operational metrics on waste management, renewable energy adoption, and local sourcing "
            "across trekking lodges in the Annapurna conservation area. (Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company08@skillmatch.local",
        "title": "Hospitality Revenue & Booking Analytics Intern",
        "category": "Hospitality and Tourism",
        "location_type": "remote",
        "stipend": Decimal("17000.00"),
        "days_to_deadline": 55,
        "total_positions": 1,
        "expected_duration": "3 months",
        "required_skills": ["Excel", "SQL"],
        "preferred_skills": ["Power BI", "Customer Service"],
        "description": (
            "Analyze historical seasonal booking trends, online travel agency commission rates, and occupancy yields "
            "to assist boutique hotels with data-informed dynamic room pricing strategies. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
    {
        "company_email": "demo.company08@skillmatch.local",
        "title": "Culinary & Event Coordination Intern",
        "category": "Hospitality and Tourism",
        "location_type": "onsite",
        "stipend": None,  # Unpaid experiential event coordination
        "days_to_deadline": 30,
        "total_positions": 2,
        "expected_duration": "2 months",
        "required_skills": ["Communication", "Customer Service"],
        "preferred_skills": ["Project Management"],
        "description": (
            "Support the planning, vendor logistics, and guest hospitality arrangements for regional cultural culinary "
            "festivals and international tourism symposiums in Pokhara. "
            "(Demonstration listing for academic supervisor review)"
        ),
    },
]

# ── 4 Separate Pending Listings (Moderation Demo) ─────────────────────────
PENDING_INTERNSHIPS = [
    {
        "company_email": "demo.company01@skillmatch.local",
        "title": "Healthcare Administration Support Intern",
        "category": "Healthcare Administration",
        "location_type": "onsite",
        "stipend": Decimal("14000.00"),
        "days_to_deadline": 45,
        "total_positions": 1,
        "expected_duration": "3 months",
        "required_skills": ["Communication", "Health Records Management"],
        "preferred_skills": ["Excel"],
        "description": (
            "Assist administrative hospital staff in digital appointment triage, patient record archiving, "
            "and clinic customer service. (Demonstration pending listing for administrator moderation review)"
        ),
    },
    {
        "company_email": "demo.company05@skillmatch.local",
        "title": "Education Programme Assistant",
        "category": "Education",
        "location_type": "hybrid",
        "stipend": Decimal("12000.00"),
        "days_to_deadline": 40,
        "total_positions": 2,
        "expected_duration": "4 months",
        "required_skills": ["Lesson Planning", "Communication"],
        "preferred_skills": ["Content Writing"],
        "description": (
            "Support community educators with after-school literacy tutoring, interactive lesson plans, and learning "
            "activity facilitation. (Demonstration pending listing for administrator moderation review)"
        ),
    },
    {
        "company_email": "demo.company03@skillmatch.local",
        "title": "Clinical Data Entry Intern",
        "category": "Healthcare Administration",
        "location_type": "remote",
        "stipend": None,
        "days_to_deadline": 50,
        "total_positions": 1,
        "expected_duration": "2 months",
        "required_skills": ["Excel", "Communication"],
        "preferred_skills": ["SQL", "Health Records Management"],
        "description": (
            "Support data quality validation, anonymized survey digitisation, and statistical data entry under strict "
            "academic medical data protocols. (Demonstration pending listing for administrator moderation review)"
        ),
    },
    {
        "company_email": "demo.company06@skillmatch.local",
        "title": "Digital Learning Content Intern",
        "category": "Education",
        "location_type": "remote",
        "stipend": Decimal("13000.00"),
        "days_to_deadline": 35,
        "total_positions": 1,
        "expected_duration": "3 months",
        "required_skills": ["Content Writing", "Figma"],
        "preferred_skills": ["Lesson Planning", "Adobe Photoshop"],
        "description": (
            "Design illustrated course slides, activity worksheets, and visual storyboards for open-access vocational "
            "e-learning portals. (Demonstration pending listing for administrator moderation review)"
        ),
    },
]

# ── 3 Student Demonstration Accounts ──────────────────────────────────────
STUDENTS = [
    {
        "email": "demo.student01@skillmatch.local",
        "department": "Computer Engineering",
        "semester": 6,
        "bio": (
            "Pre-final year engineering student specializing in full-stack Python/Django and React development. "
            "(Demonstration student account for academic supervisor matching review)"
        ),
        "skills": ["Python", "Django", "JavaScript", "React", "MySQL", "HTML", "CSS"],
        "profile_label": "Software & Web Engineering Track",
    },
    {
        "email": "demo.student02@skillmatch.local",
        "department": "Business Information Management",
        "semester": 5,
        "bio": (
            "Information systems and business analytics student focusing on SQL reporting, financial modeling, and BI. "
            "(Demonstration student account for academic supervisor matching review)"
        ),
        "skills": ["Excel", "SQL", "Power BI", "Financial Analysis", "Business Research", "Accounting"],
        "profile_label": "Data Analytics & Financial Operations Track",
    },
    {
        "email": "demo.student03@skillmatch.local",
        "department": "Media and Communication",
        "semester": 6,
        "bio": (
            "Design and communication student passionate about user interface prototyping, digital branding, and outreach. "
            "(Demonstration student account for academic supervisor matching review)"
        ),
        "skills": ["Figma", "UI/UX Design", "Adobe Photoshop", "Digital Marketing", "SEO", "Content Writing", "Communication", "Project Management"],
        "profile_label": "UI/UX Design & Digital Marketing Track",
    },
]


class Command(BaseCommand):
    help = (
        "Idempotently loads 8 fictional companies, 32 approved internships, 4 pending internships, "
        "and 3 student demo accounts for supervisor demonstration."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== SkillMatch Demo Dataset Seeder (Browse & Matching) ==="))
        self.stdout.write("Notice: Generating strictly fictional demonstration records in reserved namespace @skillmatch.local\n")

        # ── 1. Master Data (Colleges, Categories, Skills) ───────────────────
        demo_college, _ = College.objects.get_or_create(
            name="Tribhuvan University - Institute of Engineering",
            defaults={"is_verified": True}
        )
        if not demo_college.is_verified:
            demo_college.is_verified = True
            demo_college.save(update_fields=["is_verified"])

        categories_map = {}
        for cat_name in CATEGORIES_AND_SKILLS.keys():
            cat_obj, _ = Category.objects.get_or_create(name=cat_name)
            categories_map[cat_name] = cat_obj

        skills_map = {}
        for cat_name, skill_names in CATEGORIES_AND_SKILLS.items():
            cat_obj = categories_map[cat_name]
            for skill_name in skill_names:
                skill_obj, _ = Skill.objects.get_or_create(
                    name=skill_name,
                    defaults={"category": cat_obj, "is_active": True}
                )
                skills_map[skill_name] = skill_obj

        # ── 2. Companies ────────────────────────────────────────────────────
        companies_created = 0
        companies_updated = 0
        company_profiles_map = {}

        for c_data in COMPANIES:
            email = c_data["email"]
            if not email.endswith(DEMO_EMAIL_DOMAIN):
                self.stderr.write(self.style.ERROR(f"Refusing to touch non-demo email: {email}"))
                continue

            user = User.objects.filter(email=email).first()
            if user:
                if user.role != "company":
                    self.stderr.write(
                        self.style.ERROR(f"Account {email} exists with unexpected role '{user.role}'. Skipping.")
                    )
                    continue
                user.status = "active"
                user.is_active = True
                user.set_password(DEMO_PASSWORD)
                user.save()

                profile, prof_created = CompanyProfile.objects.update_or_create(
                    user=user,
                    defaults={
                        "organization_name": c_data["name"],
                        "contact_person": c_data["contact_person"],
                        "industry": c_data["industry"],
                        "hq_location": c_data["hq_location"],
                        "website_url": c_data["website_url"],
                        "description": c_data["description"],
                        "suspended": False,
                        "suspension_reason": "",
                    }
                )
                companies_updated += 1
            else:
                user = User.objects.create_user(
                    email=email,
                    password=DEMO_PASSWORD,
                    role="company",
                    status="active"
                )
                profile = CompanyProfile.objects.create(
                    user=user,
                    organization_name=c_data["name"],
                    contact_person=c_data["contact_person"],
                    industry=c_data["industry"],
                    hq_location=c_data["hq_location"],
                    website_url=c_data["website_url"],
                    description=c_data["description"],
                    suspended=False,
                )
                companies_created += 1

            # Ensure email verification token is recorded as completed
            EmailVerificationToken.objects.update_or_create(
                user=user,
                defaults={"used": True}
            )

            company_profiles_map[email] = profile

        # ── 3. Approved Internships (32) & Pending Internships (4) ─────────
        approved_created = 0
        approved_updated = 0
        pending_created = 0
        pending_updated = 0

        all_listings_data = [(item, "approved") for item in APPROVED_INTERNSHIPS] + \
                            [(item, "pending") for item in PENDING_INTERNSHIPS]

        today = date.today()

        for item, status in all_listings_data:
            company_email = item["company_email"]
            profile = company_profiles_map.get(company_email)
            if not profile:
                self.stderr.write(self.style.WARNING(f"Company {company_email} not found. Skipping listing {item['title']}"))
                continue

            category_obj = categories_map.get(item["category"])
            if not category_obj:
                category_obj, _ = Category.objects.get_or_create(name=item["category"])
                categories_map[item["category"]] = category_obj

            internship = Internship.objects.filter(company=profile, title=item["title"]).first()
            deadline = today + timedelta(days=item["days_to_deadline"])

            if internship:
                internship.description = item["description"]
                internship.category = category_obj
                internship.location_type = item["location_type"]
                internship.stipend = item["stipend"]
                internship.deadline = deadline
                internship.total_positions = item["total_positions"]
                internship.expected_duration = item["expected_duration"]
                internship.status = status
                internship.save()
                if status == "approved":
                    approved_updated += 1
                else:
                    pending_updated += 1
            else:
                internship = Internship.objects.create(
                    company=profile,
                    title=item["title"],
                    description=item["description"],
                    category=category_obj,
                    location_type=item["location_type"],
                    stipend=item["stipend"],
                    deadline=deadline,
                    total_positions=item["total_positions"],
                    expected_duration=item["expected_duration"],
                    status=status,
                )
                if status == "approved":
                    approved_created += 1
                else:
                    pending_created += 1

            # Sync Required & Preferred Skills
            if not internship.skills_locked:
                active_skill_ids = []
                for s_name in item["required_skills"]:
                    s_obj = skills_map.get(s_name)
                    if s_obj:
                        InternshipSkill.objects.update_or_create(
                            internship=internship,
                            skill=s_obj,
                            defaults={"is_required": True}
                        )
                        active_skill_ids.append(s_obj.id)
                for s_name in item["preferred_skills"]:
                    s_obj = skills_map.get(s_name)
                    if s_obj:
                        InternshipSkill.objects.update_or_create(
                            internship=internship,
                            skill=s_obj,
                            defaults={"is_required": False}
                        )
                        active_skill_ids.append(s_obj.id)
                internship.internship_skills.exclude(skill_id__in=active_skill_ids).delete()

        # ── 4. Student Accounts (3) ────────────────────────────────────────
        students_created = 0
        students_updated = 0

        for s_data in STUDENTS:
            email = s_data["email"]
            if not email.endswith(DEMO_EMAIL_DOMAIN):
                self.stderr.write(self.style.ERROR(f"Refusing to touch non-demo email: {email}"))
                continue

            user = User.objects.filter(email=email).first()
            if user:
                if user.role != "student":
                    self.stderr.write(
                        self.style.ERROR(f"Account {email} exists with unexpected role '{user.role}'. Skipping.")
                    )
                    continue
                user.status = "active"
                user.is_active = True
                user.set_password(DEMO_PASSWORD)
                user.save()

                StudentProfile.objects.update_or_create(
                    user=user,
                    defaults={
                        "college": demo_college,
                        "department": s_data["department"],
                        "semester": s_data["semester"],
                        "bio": s_data["bio"],
                        "college_verified": True,
                        "cv_file": "",  # No fake CV file attached
                    }
                )
                students_updated += 1
            else:
                user = User.objects.create_user(
                    email=email,
                    password=DEMO_PASSWORD,
                    role="student",
                    status="active"
                )
                StudentProfile.objects.create(
                    user=user,
                    college=demo_college,
                    department=s_data["department"],
                    semester=s_data["semester"],
                    bio=s_data["bio"],
                    college_verified=True,
                    cv_file="",
                )
                students_created += 1

            # Ensure email verification token is recorded as completed
            EmailVerificationToken.objects.update_or_create(
                user=user,
                defaults={"used": True}
            )

            # Sync Student Skills
            desired_skill_ids = []
            for s_name in s_data["skills"]:
                s_obj = skills_map.get(s_name)
                if s_obj:
                    StudentSkill.objects.get_or_create(student=user, skill=s_obj)
                    desired_skill_ids.append(s_obj.id)
            StudentSkill.objects.filter(student=user).exclude(skill_id__in=desired_skill_ids).delete()

        # ── 5. Output Summary ──────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS("Demo dataset operation completed successfully!\n"))
        self.stdout.write("--- Execution Summary ---")
        self.stdout.write(f"Companies:   {companies_created} created, {companies_updated} updated (Total: {len(COMPANIES)})")
        self.stdout.write(f"Approved:    {approved_created} created, {approved_updated} updated (Total: {len(APPROVED_INTERNSHIPS)})")
        self.stdout.write(f"Pending:     {pending_created} created, {pending_updated} updated (Total: {len(PENDING_INTERNSHIPS)})")
        self.stdout.write(f"Students:    {students_created} created, {students_updated} updated (Total: {len(STUDENTS)})")
        self.stdout.write(f"Skills:      {len(skills_map)} cataloged across {len(categories_map)} categories")
        self.stdout.write("")

        self.stdout.write(self.style.MIGRATE_LABEL("================ DEMO LOGIN CREDENTIALS ================"))
        self.stdout.write(f"Shared Demonstration Password: {DEMO_PASSWORD}\n")

        self.stdout.write(self.style.SUCCESS("Company Demonstration Accounts (8):"))
        for c_data in COMPANIES:
            self.stdout.write(
                f"  * {c_data['email']:<35} | {c_data['name']:<28} | {c_data['industry']}"
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Student Demonstration Accounts (3):"))
        for s_data in STUDENTS:
            skills_str = ", ".join(s_data['skills'][:4]) + "..."
            self.stdout.write(
                f"  * {s_data['email']:<35} | {s_data['profile_label']:<38} | Skills: {skills_str}"
            )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_LABEL("================ SUPERVISOR DEMONSTRATION GUIDE ================"))
        self.stdout.write("1. Internship Browsing (/student/internships/):")
        self.stdout.write("   - Displays 32 approved listings across 10 distinct professional domains.")
        self.stdout.write("   - Test filters: location (Kathmandu, Lalitpur, Pokhara, Butwal, remote),")
        self.stdout.write("     stipend (paid vs unpaid), categories, and keywords.")
        self.stdout.write("2. Personalized Skill Matching:")
        self.stdout.write("   - Log in as demo.student01@skillmatch.local to see ~80-100% matches for Python/Django & React roles.")
        self.stdout.write("   - Log in as demo.student02@skillmatch.local to see ~75-100% matches for Data Analytics & Finance roles.")
        self.stdout.write("   - Log in as demo.student03@skillmatch.local to see ~70-80% matches for UI/UX & Digital Marketing roles.")
        self.stdout.write("3. Administrator Moderation (/admin-panel/internships/):")
        self.stdout.write("   - Log in as admin to observe the 4 separate pending moderation listings ready for approval.")
        self.stdout.write("=================================================================\n")

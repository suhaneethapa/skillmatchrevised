# SkillMatch

A web-based internship management and skill-matching platform built with Django.
The system connects BIM students with companies offering internships, and matches
students to positions based on the overlap between their skills and the skills
each internship requires.

Developed as a final-year academic project.

## Features

- **Role-based accounts** — students, companies, and administrators each get
  their own dashboard and permissions.
- **Student profiles** — college, skills, and CV upload. A student must upload
  a CV before they can apply to any internship.
- **Internship listings** — companies post internships with required and
  preferred skills, positions, duration, and an application deadline. Listings
  go live only after admin approval.
- **Skill matching engine** — each student sees a match percentage on every
  listing, computed from the weighted overlap between their skills and the
  internship's skills. Students below the eligibility threshold (50%) cannot
  apply.
- **Applications and offers** — eligible students apply in one click; companies
  review applicants ranked by match score and issue offers, which students can
  view and accept.
- **Admin panel** — approve or reject pending listings, manage users, companies,
  internships, applications, and the skill catalogue, with summary statistics
  and charts.

## Tech stack

- Python 3, Django 4.2
- MySQL 8 (via mysqlclient)
- Hand-written CSS and vanilla JavaScript (no frontend frameworks)

## Project structure

- `accounts` — custom user model, registration, login, role routing
- `students` — student profiles, CV upload, browsing, applications, offers
- `companies` — company profiles, listings, applicants, offers
- `matching` — the skill-matching engine
- `admin_panel` — moderation and catalogue management
- `core` — shared models (skills, categories, colleges) and the demo seed command

## Setup (Windows)

1. Clone the repository and enter the folder.
2. Create a virtual environment and install dependencies:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Create the MySQL database:
   ```sql
   CREATE DATABASE skillmatch CHARACTER SET utf8mb4;
   ```
4. Copy `.env.example` to `.env` and fill in your database credentials and a
   secret key.
5. Apply migrations:
   ```
   python manage.py migrate
   ```
6. (Optional) Load demo data — colleges, skills, a company, sample internships
   and students:
   ```
   python manage.py seed_demo
   ```
7. Run the development server:
   ```
   python manage.py runserver
   ```

If you ran `seed_demo`, you can sign in with `admin@demo.local`,
`company@demo.local`, or `student@demo.local` — password `Demo1234!` for all
demo accounts. The demo data is fictional and intended only for testing.
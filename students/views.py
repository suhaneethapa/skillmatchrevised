from datetime import date

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.core.exceptions import ValidationError
from companies.models import Internship
from .models import Application, StudentProfile, StudentSkill
from core.models import Skill, College
from core.validators import validate_document_file
from matching.engine import compute_match_score, is_eligible
from core.emails import (
    notify_application_submitted,
    notify_offer_accepted,
    notify_offer_declined,
    notify_application_withdrawn,
    notify_listing_closed_applicants,
    notify_company_student_withdrawn_other_acceptance,
    notify_company_student_accepted_elsewhere,
)


@login_required
def dashboard(request):
    if request.user.role != 'student':
        return redirect('accounts:home')
    profile = request.user.student_profile  # <-- ADD THIS LINE
    applications = list(request.user.applications.select_related('internship__company').prefetch_related('internship__internship_skills__skill').order_by('-applied_at'))
    for app in applications:
        app.compute_current_match()
    skills_count = request.user.student_skills.count()
    return render(request, 'students/dashboard.html', {
        'profile': profile,  # <-- ADD THIS LINE
        'applications': applications,
        'skills_count': skills_count,
    })


@login_required
def profile(request):
    if request.user.role != 'student':
        return redirect('accounts:home')
    profile = request.user.student_profile
    skills = request.user.student_skills.select_related('skill__category').all()
    return render(request, 'students/profile.html', {
        'profile': profile,
        'skills': skills
    })


@login_required
def profile_edit(request):
    if request.user.role != 'student':
        return redirect('accounts:home')
    
    profile = request.user.student_profile
    colleges = College.objects.all()
    
    if request.method == 'POST':
        profile.department = request.POST.get('department', profile.department)
        profile.semester = request.POST.get('semester', profile.semester)
        profile.bio = request.POST.get('bio', profile.bio)
        profile.github_url = request.POST.get('github_url', '')
        profile.linkedin_url = request.POST.get('linkedin_url', '')
        
        college_id = request.POST.get('college')
        if college_id:
            profile.college_id = college_id
        
        if request.FILES.get('cv_file'):
            cv = request.FILES['cv_file']
            try:
                validate_document_file(cv)
                profile.cv_file = cv
            except ValidationError as e:
                messages.error(request, e.message if hasattr(e, 'message') else str(e))
                return render(request, 'students/profile_edit.html', {
                    'profile': profile,
                    'colleges': colleges
                })
        
        profile.save()
        messages.success(request, 'Profile updated successfully!')
        return redirect('students:profile')
    
    return render(request, 'students/profile_edit.html', {
        'profile': profile,
        'colleges': colleges
    })


@login_required
def skills_edit(request):
    if request.user.role != 'student':
        return redirect('accounts:home')
    
    all_skills = Skill.objects.filter(is_active=True).select_related('category').order_by('category__name', 'name')
    user_skill_ids = set(request.user.student_skills.values_list('skill_id', flat=True))
    
    if request.method == 'POST':
        selected_skill_ids = request.POST.getlist('skills')
        
        with transaction.atomic():
            request.user.student_skills.all().delete()
            for skill_id in selected_skill_ids:
                StudentSkill.objects.create(student=request.user, skill_id=skill_id)
            
            # Recompute live scores for all student applications (BUG-03)
            for app in request.user.applications.select_related('internship').prefetch_related('internship__internship_skills__skill'):
                app.compute_current_match()
        
        messages.success(request, 'Skills updated successfully!')
        return redirect('students:profile')
    
    return render(request, 'students/skills_edit.html', {
        'all_skills': all_skills,
        'user_skill_ids': user_skill_ids
    })


def browse_internships(request):
    internships = Internship.objects.filter(status='approved').select_related('company', 'category').prefetch_related('internship_skills__skill')
    today = date.today()
    
    is_student = request.user.is_authenticated and getattr(request.user, 'role', '') == 'student'
    has_cv = False
    student_skills = set()
    student_apps = {}
    
    if is_student:
        has_cv = bool(getattr(request.user, 'student_profile', None) and request.user.student_profile.cv_file)
        student_skills = set(request.user.student_skills.values_list('skill__name', flat=True))
        student_apps = {app.internship_id: app for app in request.user.applications.all()}
    
    listings_with_scores = []
    for internship in internships:
        already_applied = student_apps.get(internship.id)
        if is_student:
            req_skills = list(internship.internship_skills.values_list('skill__name', 'is_required'))
            score, gap = compute_match_score(student_skills, req_skills)
            eligible = is_eligible(score)
            if already_applied and float(already_applied.match_score) != score:
                already_applied.match_score = score
                already_applied.save(update_fields=['match_score'])
        else:
            score = None
            gap = []
            eligible = False
            
        listings_with_scores.append({
            'internship': internship,
            'score': score,
            'gap': gap,
            'eligible': eligible,
            'already_applied': already_applied,
        })
    
    if is_student:
        listings_with_scores.sort(key=lambda x: (x['score'] if x['score'] is not None else -1), reverse=True)
    else:
        listings_with_scores.sort(key=lambda x: x['internship'].created_at, reverse=True)
        
    return render(request, 'students/browse_internships.html', {
        'listings': listings_with_scores,
        'today': today,
        'is_student': is_student,
        'has_cv': has_cv,
    })


def internship_detail(request, internship_id):
    internship = get_object_or_404(
        Internship.objects.select_related('company', 'category').prefetch_related('internship_skills__skill'),
        id=internship_id,
        status='approved'
    )
    today = date.today()
    is_student = request.user.is_authenticated and getattr(request.user, 'role', '') == 'student'
    has_cv = False
    score = None
    gap = []
    eligible = False
    already_applied = None
    
    required_skills = [s.skill.name for s in internship.internship_skills.all() if s.is_required]
    preferred_skills = [s.skill.name for s in internship.internship_skills.all() if not s.is_required]
    
    if is_student:
        has_cv = bool(getattr(request.user, 'student_profile', None) and request.user.student_profile.cv_file)
        student_skills = set(request.user.student_skills.values_list('skill__name', flat=True))
        req_skills_tuples = [(s.skill.name, s.is_required) for s in internship.internship_skills.all()]
        score, gap = compute_match_score(student_skills, req_skills_tuples)
        eligible = is_eligible(score)
        already_applied = Application.objects.filter(student=request.user, internship=internship).first()
        if already_applied and float(already_applied.match_score) != score:
            already_applied.match_score = score
            already_applied.save(update_fields=['match_score'])
        matched_required = [s for s in required_skills if s in student_skills]
        missing_required = [s for s in required_skills if s not in student_skills]
        matched_preferred = [s for s in preferred_skills if s in student_skills]
    else:
        matched_required = []
        missing_required = required_skills
        matched_preferred = []
        
    return render(request, 'students/internship_detail.html', {
        'internship': internship,
        'today': today,
        'is_student': is_student,
        'has_cv': has_cv,
        'score': score,
        'gap': gap,
        'eligible': eligible,
        'already_applied': already_applied,
        'required_skills': required_skills,
        'preferred_skills': preferred_skills,
        'matched_required': matched_required,
        'missing_required': missing_required,
        'matched_preferred': matched_preferred,
    })


@login_required
def my_applications(request):
    """Redirect to dashboard — applications are shown there now."""
    if request.user.role != 'student':
        return redirect('accounts:home')
    return redirect('students:dashboard')


def apply_internship(request, internship_id):
    # Check authentication (BUG-02)
    if not request.user.is_authenticated:
        messages.info(request, "Log in or register to apply")
        request.session['intended_apply_internship_id'] = internship_id
        return redirect(f"/login/?next=/student/internships/{internship_id}/")
    
    # Check role
    if request.user.role != 'student':
        messages.error(request, "Only students can apply for internships.")
        return redirect('students:internship_detail', internship_id=internship_id)
    
    # Check approval status (BUG-09)
    if request.user.status != 'active':
        if request.user.status == 'pending_admin':
            messages.error(request, "Your account is awaiting approval")
        else:
            messages.error(request, "Your account is not active and cannot submit applications.")
        return redirect('students:internship_detail', internship_id=internship_id)
    
    # Prevent accidental GET submission / ensure idempotency
    if request.method != 'POST':
        return redirect('students:internship_detail', internship_id=internship_id)
    
    if not getattr(request.user, 'student_profile', None) or not request.user.student_profile.cv_file:
        messages.error(request, "Please upload your CV before applying.")
        return redirect('students:profile_edit')
    
    created = False
    application = None
    score = 0
    try:
        with transaction.atomic():
            # Lock the internship row to ensure consistent state inside transaction (BUG-05)
            internship = Internship.objects.select_for_update().filter(id=internship_id).first()
            if not internship:
                messages.error(request, "Internship listing not found.")
                return redirect('students:browse_internships')
            
            # Enforce listing status inside the apply transaction (BUG-05)
            if internship.status != 'approved':
                messages.error(request, "This internship listing is closed and no longer accepting applications.")
                return redirect('students:browse_internships')
            
            # Enforce deadline inside the apply transaction (BUG-05)
            if internship.deadline < date.today():
                messages.error(request, "This internship listing has closed because the application deadline has passed.")
                return redirect('students:internship_detail', internship_id=internship_id)
            
            # Check duplicate applications inside transaction (BUG-04)
            if Application.objects.filter(student=request.user, internship=internship).exists():
                messages.warning(request, "You have already applied to this internship.")
                return redirect('students:internship_detail', internship_id=internship_id)
            
            student_skills = set(request.user.student_skills.values_list('skill__name', flat=True))
            req_skills = list(internship.internship_skills.values_list('skill__name', 'is_required'))
            score, gap = compute_match_score(student_skills, req_skills)
            
            if not is_eligible(score):
                messages.error(request, f"Your match score is {score}%. You need at least 50%. Missing: {', '.join(gap) if gap else 'None'}")
                return redirect('students:internship_detail', internship_id=internship_id)
            
            application = Application(
                student=request.user,
                internship=internship,
                match_score=score,
                status='pending',
                cover_letter=request.POST.get('cover_letter', '')
            )
            application.full_clean()
            application.save()
            created = True
    except IntegrityError:
        messages.warning(request, "You have already applied to this internship.")
        return redirect('students:internship_detail', internship_id=internship_id)
    
    if created and application:
        notify_application_submitted(application)
        request.session.pop('intended_apply_internship_id', None)
        messages.success(request, f"Application submitted! Match score: {score}%")
    
    return redirect('students:dashboard')


@login_required
@require_POST
def withdraw_application(request, application_id):
    if request.user.role != 'student':
        return redirect('accounts:home')
    
    application = get_object_or_404(Application, id=application_id, student=request.user, status='pending')
    application.status = 'withdrawn'
    application.save()
    notify_application_withdrawn(application)
    messages.success(request, 'Application withdrawn successfully.')
    return redirect('students:dashboard')


@login_required
def view_offer(request, application_id):
    if request.user.role != 'student':
        return redirect('accounts:home')
    
    application = get_object_or_404(Application, id=application_id, student=request.user, status='offer_issued')
    return render(request, 'students/view_offer.html', {
        'application': application
    })


@login_required
def accept_offer(request, application_id):
    if request.user.role != 'student':
        return redirect('accounts:home')
    
    application = get_object_or_404(
        Application.objects.select_related('internship'),
        id=application_id,
        student=request.user
    )

    if application.status != 'offer_issued':
        messages.error(request, "This offer is no longer valid or has already been processed.")
        return redirect('students:dashboard')

    with transaction.atomic():
        # BUG-07: Lock internship row to close concurrency race condition on slots
        internship = Internship.objects.select_for_update().filter(id=application.internship_id).first()
        accepted_count = internship.applications.filter(status='accepted').count()
        if accepted_count >= internship.total_positions:
            messages.error(request, "Unfortunately, all positions for this internship have already been filled.")
            return redirect('students:dashboard')
        
        application.status = 'accepted'
        application.save(update_fields=['status'])

        # BUG-08: Handle other applications for this student
        other_apps = list(
            Application.objects.select_related('internship__company__user')
            .filter(student=request.user)
            .exclude(id=application.id)
        )
        for other_app in other_apps:
            if other_app.status == 'pending':
                other_app.status = 'withdrawn'
                other_app.save(update_fields=['status'])
                notify_company_student_withdrawn_other_acceptance(other_app)
            elif other_app.status == 'offer_issued':
                # Outstanding offers are NOT auto-withdrawn; notify company instead
                notify_company_student_accepted_elsewhere(other_app)

        # If all positions are now filled, close the internship and close remaining pending applications
        if accepted_count + 1 >= internship.total_positions:
            internship.status = 'closed'
            internship.save(update_fields=['status'])
            pending_apps = list(internship.applications.filter(status='pending'))
            internship.applications.filter(status='pending').update(status='rejected')
            notify_listing_closed_applicants(pending_apps, internship, reason='positions_filled')
            messages.info(request, "This internship is now closed as all positions have been filled.")

    notify_offer_accepted(application)
    messages.success(request, "Congratulations! You have accepted the offer.")
    return redirect('students:dashboard')


@login_required
def decline_offer(request, application_id):
    if request.user.role != 'student':
        return redirect('accounts:home')
    
    application = get_object_or_404(Application, id=application_id, student=request.user, status='offer_issued')
    application.status = 'rejected'
    application.save()
    notify_offer_declined(application)
    messages.success(request, "Offer declined. The company may contact other candidates.")
    return redirect('students:dashboard')
from datetime import date
import mimetypes

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.core.exceptions import ValidationError
from accounts.models import User
from companies.models import Internship
from .models import Application, StudentProfile, StudentSkill
from core.models import Skill, College, Category
from core.validators import validate_document_file
from matching.engine import compute_match_score, is_eligible, explain_match
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
    if request.user.status != 'active':
        return redirect('accounts:account_status')
    profile = request.user.student_profile
    applications = list(
        request.user.applications.select_related('internship__company')
        .prefetch_related('internship__internship_skills__skill')
        .order_by('-applied_at')
    )
    for app in applications:
        app.compute_current_match(save=False)
    skills_count = request.user.student_skills.count()

    # Placement statistics from actual database records
    total_applications = len(applications)
    pending_applications = sum(1 for a in applications if a.status == 'pending')
    rejected_applications = sum(1 for a in applications if a.status == 'rejected')
    offers_received = sum(1 for a in applications if a.status == 'offer_issued')
    accepted_offers = sum(1 for a in applications if a.status == 'accepted')

    # Identify pending offers requiring student action
    active_offers = [a for a in applications if a.status == 'offer_issued']

    # Curate relevant available internships (score >= 50%) not yet applied to
    applied_internship_ids = {a.internship_id for a in applications}
    open_listings = (
        Internship.objects.filter(status='approved', deadline__gte=date.today())
        .exclude(id__in=applied_internship_ids)
        .select_related('company', 'category')
        .prefetch_related('internship_skills__skill')
    )
    relevant_internships = []
    for item in open_listings:
        if item.remaining_positions <= 0:
            continue
        item_match = explain_match(request.user, item)
        if item_match['eligible']:
            relevant_internships.append({
                'internship': item,
                'match': item_match,
                'score': item_match['score'],
            })
    relevant_internships.sort(key=lambda x: x['score'], reverse=True)
    relevant_internships = relevant_internships[:4]

    return render(request, 'students/dashboard.html', {
        'profile': profile,
        'applications': applications,
        'skills_count': skills_count,
        'total_applications': total_applications,
        'pending_applications': pending_applications,
        'rejected_applications': rejected_applications,
        'offers_received': offers_received,
        'accepted_offers': accepted_offers,
        'active_offers': active_offers,
        'relevant_internships': relevant_internships,
    })


@login_required
def profile(request):
    if request.user.role != 'student':
        return redirect('accounts:home')
    if request.user.status != 'active':
        return redirect('accounts:account_status')
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
    if request.user.status != 'active':
        return redirect('accounts:account_status')
    
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
    if request.user.status != 'active':
        return redirect('accounts:account_status')
    
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
                app.compute_current_match(save=True)
        
        messages.success(request, 'Skills updated successfully!')
        return redirect('students:profile')
    
    return render(request, 'students/skills_edit.html', {
        'all_skills': all_skills,
        'user_skill_ids': user_skill_ids
    })


def browse_internships(request):
    internships = (
        Internship.objects.filter(status='approved')
        .select_related('company', 'category')
        .prefetch_related('internship_skills__skill')
    )
    today = date.today()

    # Retrieve filter parameters
    q = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '').strip()
    skill_id = request.GET.get('skill', '').strip()
    location = request.GET.get('location', '').strip()
    location_type = request.GET.get('location_type', '').strip()
    paid = request.GET.get('paid', '').strip()
    min_stipend = request.GET.get('min_stipend', '').strip()
    duration = request.GET.get('duration', '').strip()
    min_match = request.GET.get('min_match', '').strip()

    # 1. Keyword search (title, description, company name)
    if q:
        internships = internships.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(company__organization_name__icontains=q)
        )

    # 2. Category filter
    if category_id:
        internships = internships.filter(category_id=category_id)

    # 3. Required / listing skill filter
    if skill_id:
        internships = internships.filter(internship_skills__skill_id=skill_id)

    # 4. Location filter (company headquarters or city)
    if location:
        internships = internships.filter(company__hq_location__icontains=location)

    # 5. Location type (remote, onsite, hybrid)
    if location_type in ['remote', 'onsite', 'hybrid']:
        internships = internships.filter(location_type=location_type)

    # 6. Paid / Unpaid filter
    if paid == 'paid':
        internships = internships.filter(stipend__gt=0)
    elif paid == 'unpaid':
        internships = internships.filter(Q(stipend__isnull=True) | Q(stipend=0))

    # 7. Minimum Stipend
    if min_stipend:
        try:
            min_stipend_val = float(min_stipend)
            internships = internships.filter(stipend__gte=min_stipend_val)
        except ValueError:
            pass

    # 8. Duration filter
    if duration:
        internships = internships.filter(expected_duration__icontains=duration)

    internships = internships.distinct()

    is_student = request.user.is_authenticated and getattr(request.user, 'role', '') == 'student'
    has_cv = False
    student_apps = {}

    if is_student:
        has_cv = bool(getattr(request.user, 'student_profile', None) and request.user.student_profile.cv_file)
        student_apps = {app.internship_id: app for app in request.user.applications.all()}

    # Parse min_match filter for logged-in students
    min_match_val = None
    if is_student and min_match:
        try:
            min_match_val = float(min_match)
        except ValueError:
            min_match_val = None

    listings_with_scores = []
    for internship in internships:
        already_applied = student_apps.get(internship.id)
        if is_student:
            match = explain_match(request.user, internship)
            score = match['score']
            gap = match['gap']
            eligible = match['eligible']

            # Minimum match filter check
            if min_match_val is not None and score < min_match_val:
                continue

            if already_applied:
                already_applied.match_score = score
        else:
            score = None
            gap = []
            eligible = False
            match = None

        listings_with_scores.append({
            'internship': internship,
            'score': score,
            'gap': gap,
            'eligible': eligible,
            'match': match,
            'already_applied': already_applied,
        })

    if is_student:
        listings_with_scores.sort(key=lambda x: (x['score'] if x['score'] is not None else -1), reverse=True)
    else:
        listings_with_scores.sort(key=lambda x: x['internship'].created_at, reverse=True)

    categories = Category.objects.all().order_by('name')
    skills = Skill.objects.filter(is_active=True).order_by('name')

    return render(request, 'students/browse_internships.html', {
        'listings': listings_with_scores,
        'today': today,
        'is_student': is_student,
        'has_cv': has_cv,
        'categories': categories,
        'skills': skills,
        'q': q,
        'selected_category': category_id,
        'selected_skill': skill_id,
        'selected_location': location,
        'selected_location_type': location_type,
        'selected_paid': paid,
        'selected_min_stipend': min_stipend,
        'selected_duration': duration,
        'selected_min_match': min_match,
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
    match = None

    required_skills = [s.skill.name for s in internship.internship_skills.all() if s.is_required]
    preferred_skills = [s.skill.name for s in internship.internship_skills.all() if not s.is_required]

    if is_student:
        has_cv = bool(getattr(request.user, 'student_profile', None) and request.user.student_profile.cv_file)
        match = explain_match(request.user, internship)
        score = match['score']
        gap = match['gap']
        eligible = match['eligible']
        matched_required = match['matched_required']
        missing_required = match['missing_required']
        matched_preferred = match['matched_preferred']
        missing_preferred = match['missing_preferred']

        already_applied = Application.objects.filter(student=request.user, internship=internship).first()
        if already_applied:
            already_applied.match_score = score
    else:
        matched_required = []
        missing_required = required_skills
        matched_preferred = []
        missing_preferred = preferred_skills

    return render(request, 'students/internship_detail.html', {
        'internship': internship,
        'today': today,
        'is_student': is_student,
        'has_cv': has_cv,
        'score': score,
        'gap': gap,
        'eligible': eligible,
        'match': match,
        'already_applied': already_applied,
        'required_skills': required_skills,
        'preferred_skills': preferred_skills,
        'matched_required': matched_required,
        'missing_required': missing_required,
        'matched_preferred': matched_preferred,
        'missing_preferred': missing_preferred,
    })


@login_required
def my_applications(request):
    """Redirect to dashboard — applications are shown there now."""
    if request.user.role != 'student':
        return redirect('accounts:home')
    if request.user.status != 'active':
        return redirect('accounts:account_status')
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
        elif request.user.status == 'pending_email':
            messages.error(request, "Please verify your email address before applying.")
        else:
            messages.error(request, "Your account is not active and cannot submit applications.")
        return redirect('students:internship_detail', internship_id=internship_id)
    
    # Check college verification (A2)
    profile = getattr(request.user, 'student_profile', None)
    if not profile or not profile.college_verified:
        messages.error(request, "Your college affiliation is pending verification by the administrator.")
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
    if request.user.status != 'active':
        return redirect('accounts:account_status')
    
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
    if request.user.status != 'active':
        return redirect('accounts:account_status')
    
    application = get_object_or_404(Application, id=application_id, student=request.user, status='offer_issued')
    return render(request, 'students/view_offer.html', {
        'application': application
    })


@login_required
@require_POST
def accept_offer(request, application_id):
    if request.user.role != 'student':
        return redirect('accounts:home')
    if request.user.status != 'active':
        return redirect('accounts:account_status')
    
    with transaction.atomic():
        # Phase 3 / A9: Lock Application record inside transaction to close concurrency races
        application = (
            Application.objects.select_for_update()
            .filter(id=application_id, student=request.user)
            .first()
        )
        if not application:
            return redirect('students:dashboard')

        if application.status != 'offer_issued':
            messages.error(request, "This offer is no longer valid or has already been processed.")
            return redirect('students:dashboard')

        # Lock internship row to close concurrency race condition on slots
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
                transaction.on_commit(lambda app=other_app: notify_company_student_withdrawn_other_acceptance(app))
            elif other_app.status == 'offer_issued':
                # Outstanding offers are NOT auto-withdrawn; notify company instead
                transaction.on_commit(lambda app=other_app: notify_company_student_accepted_elsewhere(app))

        # If all positions are now filled, close the internship and close remaining pending applications
        if accepted_count + 1 >= internship.total_positions:
            internship.status = 'closed'
            internship.save(update_fields=['status'])
            pending_apps = list(internship.applications.filter(status='pending'))
            internship.applications.filter(status='pending').update(status='rejected')
            transaction.on_commit(lambda p_apps=pending_apps, itn=internship: notify_listing_closed_applicants(p_apps, itn, reason='positions_filled'))
            messages.info(request, "This internship is now closed as all positions have been filled.")

        transaction.on_commit(lambda app=application: notify_offer_accepted(app))

    messages.success(request, "Congratulations! You have accepted the offer.")
    return redirect('students:dashboard')


@login_required
@require_POST
def decline_offer(request, application_id):
    if request.user.role != 'student':
        return redirect('accounts:home')
    if request.user.status != 'active':
        return redirect('accounts:account_status')
    
    with transaction.atomic():
        application = (
            Application.objects.select_for_update()
            .filter(id=application_id, student=request.user)
            .first()
        )
        if not application:
            return redirect('students:dashboard')

        if application.status != 'offer_issued':
            messages.error(request, "This offer is no longer valid or has already been processed.")
            return redirect('students:dashboard')

        application.status = 'rejected'
        application.save(update_fields=['status'])
        transaction.on_commit(lambda app=application: notify_offer_declined(app))

    messages.success(request, "Offer declined. The company may contact other candidates.")
    return redirect('students:dashboard')


@login_required
def view_cv(request, student_id=None):
    """
    Authenticated access to a student's CV.
    Permissions:
      - Student viewing their own CV.
      - Authorized company viewing CV of a candidate who applied to one of their internships.
      - Administrator.
    """
    if request.user.role == 'student' and request.user.status != 'active':
        return redirect('accounts:account_status')

    if student_id is None:
        target_user = request.user
    else:
        target_user = get_object_or_404(User, id=student_id, role='student')

    is_admin = request.user.is_staff or request.user.is_superuser or getattr(request.user, 'role', '') == 'admin'
    is_owner = (request.user == target_user)
    is_authorized_company = False

    if request.user.role == 'company':
        from companies.views import is_company_authorized
        if is_company_authorized(request):
            has_applied = Application.objects.filter(
                student=target_user,
                internship__company=request.user.company_profile
            ).exists()
            if has_applied:
                is_authorized_company = True

    if not (is_admin or is_owner or is_authorized_company):
        return HttpResponseForbidden("You do not have permission to access this CV document.")

    profile = getattr(target_user, 'student_profile', None)
    if not profile or not profile.cv_file:
        raise Http404("CV document not found.")

    cv_file = profile.cv_file
    if not cv_file.storage.exists(cv_file.name):
        raise Http404("CV document file does not exist on storage.")

    content_type, _ = mimetypes.guess_type(cv_file.name)
    response = FileResponse(cv_file.open('rb'), content_type=content_type or 'application/pdf')
    response['Content-Disposition'] = f'inline; filename="{cv_file.name.split("/")[-1]}"'
    return response


@login_required
def view_my_cv(request):
    """Convenience endpoint for student to view their own uploaded CV."""
    if request.user.role != 'student':
        return HttpResponseForbidden("Only students have a personal CV.")
    if request.user.status != 'active':
        return redirect('accounts:account_status')
    return view_cv(request, student_id=request.user.id)


@login_required
def view_offer_letter(request, application_id):
    """
    Authenticated access to an application's offer letter.
    Permissions:
      - Student applicant on the application.
      - Authorized offering company owning the internship.
      - Administrator.
    """
    if request.user.role == 'student' and request.user.status != 'active':
        return redirect('accounts:account_status')

    application = get_object_or_404(
        Application.objects.select_related('student', 'internship__company__user'),
        id=application_id
    )

    is_admin = request.user.is_staff or request.user.is_superuser or getattr(request.user, 'role', '') == 'admin'
    is_student_applicant = (request.user == application.student)
    is_offering_company = False

    if request.user.role == 'company':
        from companies.views import is_company_authorized
        if is_company_authorized(request) and application.internship.company.user == request.user:
            is_offering_company = True

    if not (is_admin or is_student_applicant or is_offering_company):
        return HttpResponseForbidden("You do not have permission to access this offer letter.")

    if not application.offer_letter:
        raise Http404("No offer letter attached to this application.")

    offer_file = application.offer_letter
    if not offer_file.storage.exists(offer_file.name):
        raise Http404("Offer letter document file does not exist on storage.")

    content_type, _ = mimetypes.guess_type(offer_file.name)
    response = FileResponse(offer_file.open('rb'), content_type=content_type or 'application/pdf')
    response['Content-Disposition'] = f'inline; filename="{offer_file.name.split("/")[-1]}"'
    return response

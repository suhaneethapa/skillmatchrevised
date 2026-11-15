from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from datetime import date
from .models import Internship, InternshipSkill, CompanyProfile
from core.models import Skill, Category
from students.models import Application
from core.emails import notify_offer_issued, notify_application_rejected
from matching.engine import compute_match_score
from core.validators import validate_document_file
from .forms import InternshipForm, IssueOfferForm


@login_required
def dashboard(request):
    if request.user.role != 'company':
        return redirect('accounts:home')
    
    profile = request.user.company_profile
    internships = profile.internships.all()
    return render(request, 'companies/dashboard.html', {
        'internships': internships,
        'profile': profile,
        'today': date.today(),
    })


@login_required
def profile(request):
    if request.user.role != 'company':
        return redirect('accounts:home')
    
    profile = request.user.company_profile
    return render(request, 'companies/profile.html', {
        'profile': profile,
    })


@login_required
def profile_edit(request):
    if request.user.role != 'company':
        return redirect('accounts:home')
    
    profile = request.user.company_profile
    
    if request.method == 'POST':
        profile.organization_name = request.POST.get('organization_name', profile.organization_name)
        profile.contact_person = request.POST.get('contact_person', profile.contact_person)
        profile.industry = request.POST.get('industry', profile.industry)
        profile.description = request.POST.get('description', profile.description)
        profile.website_url = request.POST.get('website_url', '')
        profile.hq_location = request.POST.get('hq_location', profile.hq_location)
        
        if request.FILES.get('logo'):
            logo = request.FILES['logo']
            
            if logo.size > 2 * 1024 * 1024:
                messages.error(request, 'Logo file too large. Maximum size is 2MB.')
                return redirect('companies:profile_edit')
            
            if not logo.content_type.startswith('image/'):
                messages.error(request, 'Only image files (PNG, JPG, GIF) are allowed for logo.')
                return redirect('companies:profile_edit')
            
            profile.logo = logo
            messages.success(request, 'Logo uploaded successfully!')
        
        profile.save()
        messages.success(request, 'Company profile updated successfully!')
        return redirect('companies:profile')
    
    return render(request, 'companies/profile_edit.html', {
        'profile': profile,
    })


@login_required
def my_listings(request):
    if request.user.role != 'company':
        return redirect('accounts:home')
    
    internships = request.user.company_profile.internships.all()
    return render(request, 'companies/listings.html', {
        'internships': internships,
        'today': date.today(),
    })


@login_required
def create_listing(request):
    if request.user.role != 'company':
        return redirect('accounts:home')
    
    skills = Skill.objects.filter(is_active=True)
    categories = Category.objects.all()
    
    if request.method == 'POST':
        form = InternshipForm(request.POST)
        required_skills = request.POST.getlist('required_skills')
        preferred_skills = request.POST.getlist('preferred_skills')
        
        if not required_skills:
            messages.error(request, "Please select at least one required skill.")
            return render(request, 'companies/create_listing.html', {
                'skills': skills,
                'categories': categories
            })
            
        if form.is_valid():
            internship = form.save(commit=False)
            internship.company = request.user.company_profile
            internship.status = 'approved'
            internship.save()
            
            for skill_id in required_skills:
                InternshipSkill.objects.create(internship=internship, skill_id=skill_id, is_required=True)
            for skill_id in preferred_skills:
                InternshipSkill.objects.create(internship=internship, skill_id=skill_id, is_required=False)
            
            messages.success(request, "Internship posted successfully!")
            return redirect('companies:dashboard')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
            return render(request, 'companies/create_listing.html', {
                'skills': skills,
                'categories': categories
            })
    
    return render(request, 'companies/create_listing.html', {
        'skills': skills,
        'categories': categories
    })


@login_required
def edit_listing(request, internship_id):
    if request.user.role != 'company':
        return redirect('accounts:home')
    
    internship = get_object_or_404(
        Internship.objects.prefetch_related('internship_skills'),
        id=internship_id,
        company=request.user.company_profile
    )
    skills = Skill.objects.filter(is_active=True)
    categories = Category.objects.all()
    skills_locked = internship.skills_locked

    existing_required_ids = set(
        internship.internship_skills.filter(is_required=True).values_list('skill_id', flat=True)
    )
    existing_preferred_ids = set(
        internship.internship_skills.filter(is_required=False).values_list('skill_id', flat=True)
    )

    if request.method == 'POST':
        form = InternshipForm(request.POST, instance=internship)
        submitted_required = set(int(s) for s in request.POST.getlist('required_skills') if s.isdigit())
        submitted_preferred = set(int(s) for s in request.POST.getlist('preferred_skills') if s.isdigit())

        # BUG-06: Check if skills are locked
        if skills_locked:
            if submitted_required != existing_required_ids or submitted_preferred != existing_preferred_ids:
                messages.error(
                    request,
                    "Listing skills are locked because applications have already been received. "
                    "Close and repost the internship if requirements changed."
                )
                return redirect('companies:edit_listing', internship_id=internship.id)

        if form.is_valid():
            internship = form.save()

            # If not locked, update skills
            if not skills_locked:
                internship.internship_skills.all().delete()
                for s_id in submitted_required:
                    InternshipSkill.objects.create(internship=internship, skill_id=s_id, is_required=True)
                for s_id in submitted_preferred:
                    InternshipSkill.objects.create(internship=internship, skill_id=s_id, is_required=False)

            messages.success(request, "Internship updated successfully!")
            return redirect('companies:my_listings')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
            return render(request, 'companies/edit_listing.html', {
                'internship': internship,
                'skills': skills,
                'categories': categories,
                'skills_locked': skills_locked,
                'existing_required_ids': existing_required_ids,
                'existing_preferred_ids': existing_preferred_ids,
            })

    return render(request, 'companies/edit_listing.html', {
        'internship': internship,
        'skills': skills,
        'categories': categories,
        'skills_locked': skills_locked,
        'existing_required_ids': existing_required_ids,
        'existing_preferred_ids': existing_preferred_ids,
    })


@login_required
def delete_listing(request, internship_id):
    if request.user.role != 'company':
        return redirect('accounts:home')
    
    internship = get_object_or_404(Internship, id=internship_id, company=request.user.company_profile)
    
    if request.method == 'POST':
        internship.delete()
        messages.success(request, "Internship listing deleted successfully.")
        return redirect('companies:my_listings')
    
    return render(request, 'companies/confirm_delete.html', {
        'internship': internship,
    })


@login_required
def view_applicants(request, internship_id):
    if request.user.role != 'company':
        return redirect('accounts:home')
    
    internship = get_object_or_404(
        Internship.objects.prefetch_related('internship_skills__skill'),
        id=internship_id,
        company=request.user.company_profile
    )
    req_skills = list(internship.internship_skills.values_list('skill__name', 'is_required'))
    applications = list(internship.applications.select_related('student__student_profile').prefetch_related('student__student_skills__skill').all())
    
    # Recompute live match score for each applicant (BUG-03)
    for app in applications:
        student_skills = set(app.student.student_skills.values_list('skill__name', flat=True))
        current_score, gap = compute_match_score(student_skills, req_skills)
        if float(app.match_score) != current_score:
            app.match_score = current_score
            app.save(update_fields=['match_score'])
        app.current_score = current_score
    
    applications.sort(key=lambda a: float(a.match_score), reverse=True)
    
    return render(request, 'companies/applicants.html', {
        'internship': internship,
        'applications': applications
    })


@login_required
def issue_offer(request, application_id):
    if request.user.role != 'company':
        return redirect('accounts:home')
    
    application = get_object_or_404(
        Application.objects.select_related('internship'),
        id=application_id,
        internship__company=request.user.company_profile
    )
    internship = application.internship

    # BUG-07: Listing must be Open (approved, deadline not passed, positions remain)
    if internship.status != 'approved':
        messages.error(request, "Cannot issue offers for an internship listing that is not open.")
        return redirect('companies:view_applicants', internship_id=internship.id)

    if internship.deadline < date.today():
        messages.error(request, "Cannot issue offers because this internship listing deadline has passed.")
        return redirect('companies:view_applicants', internship_id=internship.id)

    if internship.remaining_positions <= 0:
        messages.error(request, "Cannot issue offers because all positions for this listing have been filled.")
        return redirect('companies:view_applicants', internship_id=internship.id)

    # BUG-07: Application must be in Pending status
    if application.status != 'pending':
        messages.error(request, f"Cannot issue an offer for an application in '{application.get_status_display()}' status.")
        return redirect('companies:view_applicants', internship_id=internship.id)
    
    if request.method == 'POST':
        if request.FILES.get('offer_letter'):
            offer_file = request.FILES['offer_letter']
            try:
                validate_document_file(offer_file)
                application.offer_letter = offer_file
            except ValidationError as e:
                messages.error(request, e.message if hasattr(e, 'message') else str(e))
                return render(request, 'companies/issue_offer.html', {
                    'application': application
                })
        
        application.status = 'offer_issued'
        application.save()
        notify_offer_issued(application)
        
        messages.success(request, "Offer letter issued successfully!")
        return redirect('companies:view_applicants', internship_id=application.internship.id)
    
    return render(request, 'companies/issue_offer.html', {
        'application': application
    })


@login_required
def reject_applicant(request, application_id):
    if request.user.role != 'company':
        return redirect('accounts:home')
    
    application = get_object_or_404(Application, id=application_id, internship__company=request.user.company_profile)
    
    if application.status not in ['pending', 'offer_issued']:
        messages.error(request, f"Cannot reject application in '{application.get_status_display()}' status.")
        return redirect('companies:view_applicants', internship_id=application.internship.id)
    
    valid_reasons = [choice[0] for choice in Application.REJECTION_REASONS]
    
    if request.method == 'POST':
        reason = request.POST.get('rejection_reason', '').strip()
        feedback = request.POST.get('feedback', '').strip()
        
        if not reason or reason not in valid_reasons:
            messages.error(request, "Please select a valid rejection reason from the list.")
            return render(request, 'companies/reject_applicant.html', {
                'application': application,
                'rejection_reasons': Application.REJECTION_REASONS,
                'selected_reason': reason,
                'feedback': feedback,
            })
        
        application.status = 'rejected'
        application.rejection_reason = reason
        application.rejection_feedback = feedback
        application.save()
        
        notify_application_rejected(application, reason=reason, feedback=feedback)
        messages.success(request, f"Applicant {application.student.email} has been rejected.")
        return redirect('companies:view_applicants', internship_id=application.internship.id)
    
    return render(request, 'companies/reject_applicant.html', {
        'application': application,
        'rejection_reasons': Application.REJECTION_REASONS,
    })

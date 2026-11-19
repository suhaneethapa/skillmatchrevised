from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.core.cache import cache
from django.db import transaction
from .models import EmailVerificationToken
from .forms import StudentRegistrationForm, CompanyRegistrationForm, LoginForm
from core.emails import notify_email_verification


def is_safe_redirect_url(url, request):
    """
    Validates redirect URLs:
    - Must pass Django's url_has_allowed_host_and_scheme with the current host.
    - Rejects external domains and protocol-relative URLs.
    - Rejects backslash-based and URL-encoded backslash payloads.
    """
    if not url:
        return False
    if '\\' in url or '%5c' in url.lower():
        return False
    return url_has_allowed_host_and_scheme(
        url=url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    )


def home(request):
    if request.user.is_authenticated:
        if request.user.role == 'student':
            if request.user.status != 'active':
                return redirect('accounts:account_status')
            return redirect('students:dashboard')
        elif request.user.role == 'company':
            if request.user.status != 'active':
                return redirect('accounts:account_status')
            return redirect('companies:dashboard')
        elif request.user.role == 'admin':
            return redirect('admin_panel:dashboard')
    return render(request, 'accounts/home.html')


@login_required
def account_status(request):
    """
    Renders account status and verification information for pending or rejected accounts.
    Active accounts are redirected to their respective dashboards.
    """
    if request.user.status == 'active':
        if request.user.role == 'student':
            return redirect('students:dashboard')
        elif request.user.role == 'company':
            return redirect('companies:dashboard')
        elif request.user.role == 'admin':
            return redirect('admin_panel:dashboard')

    return render(request, 'accounts/account_status.html', {
        'user': request.user,
        'status': request.user.status,
    })


def register(request):
    student_form = StudentRegistrationForm()
    company_form = CompanyRegistrationForm()
    next_url = request.GET.get('next') or request.POST.get('next')
    
    if request.method == 'POST':
        if request.POST.get('role') == 'student':
            student_form = StudentRegistrationForm(request.POST)
            if student_form.is_valid():
                user = student_form.save()
                token_obj = EmailVerificationToken.objects.create(user=user)
                verification_url = request.build_absolute_uri(
                    reverse('accounts:verify_email', args=[token_obj.token])
                )
                notify_email_verification(user, verification_url)
                login(request, user)
                messages.success(request, "Registration successful! Welcome to SkillMatch. A verification link has been sent to your email. Your college affiliation is pending verification.")
                intended_id = request.session.pop('intended_apply_internship_id', None)
                if next_url and is_safe_redirect_url(next_url, request):
                    return redirect(next_url)
                if intended_id:
                    return redirect('students:internship_detail', internship_id=intended_id)
                return redirect('accounts:account_status')
        else:
            company_form = CompanyRegistrationForm(request.POST)
            if company_form.is_valid():
                user = company_form.save()
                token_obj = EmailVerificationToken.objects.create(user=user)
                verification_url = request.build_absolute_uri(
                    reverse('accounts:verify_email', args=[token_obj.token])
                )
                notify_email_verification(user, verification_url)
                messages.success(request, "Company registration submitted! A verification link has been sent to your email. Your account is pending administrator approval.")
                if next_url and is_safe_redirect_url(next_url, request):
                    return redirect(next_url)
                return redirect('accounts:login')
    
    return render(request, 'accounts/register.html', {
        'student_form': student_form,
        'company_form': company_form,
        'next': next_url,
    })


def login_view(request):
    form = LoginForm()
    error = None
    next_url = request.GET.get('next') or request.POST.get('next')
    
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email'].strip().lower()
            password = form.cleaned_data['password']
            
            lockout_key = f"login_lockout_{email}"
            attempts_key = f"login_attempts_{email}"
            
            if cache.get(lockout_key):
                error = "Account is locked due to too many failed login attempts. Please try again in 5 minutes."
            else:
                user = authenticate(request, username=email, password=password)
                if user:
                    cache.delete(attempts_key)
                    cache.delete(lockout_key)
                    login(request, user)
                    if user.status != 'active' and user.role != 'admin':
                        return redirect('accounts:account_status')
                    if user.role == 'student':
                        intended_id = request.session.pop('intended_apply_internship_id', None)
                        if next_url and is_safe_redirect_url(next_url, request):
                            return redirect(next_url)
                        if intended_id:
                            return redirect('students:internship_detail', internship_id=intended_id)
                        return redirect('students:dashboard')
                    elif user.role == 'company':
                        if next_url and is_safe_redirect_url(next_url, request):
                            return redirect(next_url)
                        return redirect('companies:dashboard')
                    else:
                        if next_url and is_safe_redirect_url(next_url, request):
                            return redirect(next_url)
                        return redirect('admin_panel:dashboard')
                else:
                    failed_attempts = cache.get(attempts_key, 0) + 1
                    if failed_attempts >= 5:
                        cache.set(lockout_key, True, timeout=300)
                        cache.delete(attempts_key)
                        error = "Account is locked due to too many failed login attempts. Please try again in 5 minutes."
                    else:
                        cache.set(attempts_key, failed_attempts, timeout=300)
                        error = "Invalid email or password"
    
    return render(request, 'accounts/login.html', {'form': form, 'error': error, 'next': next_url})


@login_required
@require_POST
def logout_view(request):
    logout(request)
    return redirect('accounts:home')


def verify_email(request, token):
    # GET request pre-check (must not mutate database state)
    token_obj = EmailVerificationToken.objects.select_related('user').filter(token=token).first()
    if not token_obj:
        return render(request, 'accounts/verify.html', {
            'valid': False,
            'error_title': 'Invalid Verification Link',
            'error_message': 'This email verification link is invalid or does not exist.',
        })

    if token_obj.used:
        return render(request, 'accounts/verify.html', {
            'valid': False,
            'error_title': 'Verification Link Already Used',
            'error_message': 'This email verification link has already been used. Please log in to your account.',
        })

    if token_obj.is_expired:
        return render(request, 'accounts/verify.html', {
            'valid': False,
            'error_title': 'Verification Link Expired',
            'error_message': 'This email verification link has expired. Verification links are valid for 24 hours.',
        })

    if request.method == 'POST':
        with transaction.atomic():
            locked_token = (
                EmailVerificationToken.objects.select_for_update()
                .select_related('user')
                .filter(token=token)
                .first()
            )
            if not locked_token:
                return render(request, 'accounts/verify.html', {
                    'valid': False,
                    'error_title': 'Invalid Verification Link',
                    'error_message': 'This email verification link is invalid or does not exist.',
                })

            if locked_token.used:
                return render(request, 'accounts/verify.html', {
                    'valid': False,
                    'error_title': 'Verification Link Already Used',
                    'error_message': 'This email verification link has already been used. Please log in to your account.',
                })

            if locked_token.is_expired:
                return render(request, 'accounts/verify.html', {
                    'valid': False,
                    'error_title': 'Verification Link Expired',
                    'error_message': 'This email verification link has expired. Verification links are valid for 24 hours.',
                })

            user = locked_token.user
            locked_token.used = True
            locked_token.save(update_fields=['used'])

            if user.status == 'pending_email':
                user.status = 'pending_admin'
                user.save(update_fields=['status'])

        messages.success(request, "Email address verified successfully! Your account is now pending administrator approval.")
        return redirect('accounts:login')

    return render(request, 'accounts/verify.html', {
        'valid': True,
        'user_email': token_obj.user.email,
        'token': token,
    })


class SkillMatchPasswordResetView(auth_views.PasswordResetView):
    template_name = 'accounts/password_reset.html'
    email_template_name = 'accounts/password_reset_email.txt'
    subject_template_name = 'accounts/password_reset_subject.txt'
    success_url = reverse_lazy('accounts:password_reset_done')


class SkillMatchPasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'accounts/password_reset_done.html'


class SkillMatchPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    success_url = reverse_lazy('accounts:password_reset_complete')


class SkillMatchPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'accounts/password_reset_complete.html'


password_reset_request = SkillMatchPasswordResetView.as_view()
password_reset_done = SkillMatchPasswordResetDoneView.as_view()
password_reset_confirm = SkillMatchPasswordResetConfirmView.as_view()
password_reset_complete = SkillMatchPasswordResetCompleteView.as_view()

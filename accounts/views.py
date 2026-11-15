from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.urls import reverse_lazy
from django.core.cache import cache
from .forms import StudentRegistrationForm, CompanyRegistrationForm, LoginForm


def home(request):
    if request.user.is_authenticated:
        if request.user.role == 'student':
            return redirect('students:dashboard')
        elif request.user.role == 'company':
            return redirect('companies:dashboard')
        elif request.user.role == 'admin':
            return redirect('admin_panel:dashboard')
    return render(request, 'accounts/home.html')


def register(request):
    student_form = StudentRegistrationForm()
    company_form = CompanyRegistrationForm()
    next_url = request.GET.get('next') or request.POST.get('next')
    
    if request.method == 'POST':
        if request.POST.get('role') == 'student':
            student_form = StudentRegistrationForm(request.POST)
            if student_form.is_valid():
                user = student_form.save()
                login(request, user)
                messages.success(request, "Registration successful! Welcome to SkillMatch.")
                intended_id = request.session.pop('intended_apply_internship_id', None)
                if next_url and next_url.startswith('/'):
                    return redirect(next_url)
                if intended_id:
                    return redirect('students:internship_detail', internship_id=intended_id)
                return redirect('students:dashboard')
        else:
            company_form = CompanyRegistrationForm(request.POST)
            if company_form.is_valid():
                company_form.save()
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
                    if user.role == 'student':
                        intended_id = request.session.pop('intended_apply_internship_id', None)
                        if next_url and next_url.startswith('/'):
                            return redirect(next_url)
                        if intended_id:
                            return redirect('students:internship_detail', internship_id=intended_id)
                        return redirect('students:dashboard')
                    elif user.role == 'company':
                        return redirect('companies:dashboard')
                    else:
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
def logout_view(request):
    logout(request)
    return redirect('accounts:home')


def verify_email(request, token):
    # token captured from URL for future verification logic
    return render(request, 'accounts/verify.html', {'token': token})


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
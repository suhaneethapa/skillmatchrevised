from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth import logout
from django.contrib import messages
from django.shortcuts import redirect


class NoCacheMiddleware(MiddlewareMixin):
    """
    Prevent browser from caching pages for authenticated users.
    This stops the 'ghost listing' bug when using the back button
    after creating or deleting content.
    """
    def process_response(self, request, response):
        if request.user.is_authenticated:
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
        return response


class AccountStatusMiddleware:
    """
    Enforces account status restrictions across workspaces:
    - Suspended accounts are logged out immediately and redirected to login.
    - Pending-email, pending-admin, and rejected student accounts are restricted
      from all student workspace routes except public internship browsing and detail.
    - Pending-email, pending-admin, and rejected company accounts are restricted
      from all company workspace routes.
    - Redirects restricted requests to accounts:account_status.
    - Administrators and active accounts retain full access.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Administrators and superusers are never restricted
            if request.user.is_superuser or getattr(request.user, 'role', '') == 'admin':
                return self.get_response(request)

            status = getattr(request.user, 'status', None)

            # 1. User suspension
            if status == 'suspended':
                logout(request)
                messages.error(request, "Your account has been suspended by the administrator.")
                return redirect('accounts:login')

            # 2. Company profile suspension
            if getattr(request.user, 'role', '') == 'company':
                profile = getattr(request.user, 'company_profile', None)
                if profile and profile.suspended:
                    logout(request)
                    messages.error(request, "Your company account has been suspended by the administrator.")
                    return redirect('accounts:login')

            path = request.path_info

            # Excluded auth/public endpoints
            exempt_prefixes = [
                '/status/',
                '/verify/',
                '/logout/',
                '/login/',
                '/register/',
                '/password-reset/',
                '/static/',
                '/media/',
            ]
            if any(path.startswith(prefix) for prefix in exempt_prefixes):
                return self.get_response(request)

            # 3. For pending_email, pending_admin, or rejected student accounts:
            # Block access to all student workspace routes EXCEPT public internship discovery/detail and apply endpoint
            # (apply endpoint enforces approval status at view level with precise warning messages and detail redirects)
            if getattr(request.user, 'role', '') == 'student' and status in ['pending_email', 'pending_admin', 'rejected']:
                if (
                    path.startswith('/student/')
                    and not path.startswith('/student/internships/')
                    and not path.startswith('/student/apply/')
                ):
                    return redirect('accounts:account_status')

            # 4. For pending_email, pending_admin, or rejected company accounts:
            # Block all company workspace routes
            if getattr(request.user, 'role', '') == 'company' and status in ['pending_email', 'pending_admin', 'rejected']:
                if path.startswith('/company/'):
                    return redirect('accounts:account_status')

        response = self.get_response(request)
        return response

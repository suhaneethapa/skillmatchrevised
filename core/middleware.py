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
    BUG-09: Enforces account status restrictions and invalidates sessions
    for suspended users and suspended companies immediately.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_superuser:
            # Check user-level suspension
            if getattr(request.user, 'status', None) == 'suspended':
                logout(request)
                messages.error(request, "Your account has been suspended by the administrator.")
                return redirect('accounts:login')
            
            # Check company-level suspension
            if getattr(request.user, 'role', '') == 'company':
                profile = getattr(request.user, 'company_profile', None)
                if profile and profile.suspended:
                    logout(request)
                    messages.error(request, "Your company account has been suspended by the administrator.")
                    return redirect('accounts:login')

        response = self.get_response(request)
        return response

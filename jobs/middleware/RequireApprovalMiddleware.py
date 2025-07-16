from django.shortcuts import render
from django.urls import reverse

class RequireApprovalMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            if request.user.is_superuser or request.user.is_staff:
                return self.get_response(request)

            if hasattr(request.user, 'userprofile') and not request.user.userprofile.is_approved:
                if request.path not in [reverse('logout'), reverse('profile')]:
                    return render(request, 'jobs/403.html', {
                        'message': "Your account is awaiting admin approval."
                    }, status=403)

        return self.get_response(request)

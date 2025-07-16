from django.contrib.auth import logout
from django.contrib.sessions.models import Session
from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth.models import User

class SingleSessionMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.user.is_authenticated:
            # Get all sessions
            user_sessions = Session.objects.filter(expire_date__gte=request.session.get_expiry_date())
            for session in user_sessions:
                data = session.get_decoded()
                if data.get('_auth_user_id') == str(request.user.id):
                    if session.session_key != request.session.session_key:
                        # Delete previous session
                        session.delete()

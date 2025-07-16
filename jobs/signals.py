from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.contrib.sessions.models import Session
from django.contrib.auth import logout
from django.core.mail import send_mail
from django.conf import settings
from allauth.account.signals import user_signed_up
from django.contrib.auth import login
from allauth.account.signals import user_logged_in as allauth_logged_in

import logging

from .models import UserSession, UserProfile

logger = logging.getLogger(__name__)



@receiver(user_logged_out)
def clear_user_session(sender, request, user, **kwargs):
    logger.info(f"user_logged_out signal triggered for {user.username}")

    try:
        # Delete user session entry regardless of session_key
        UserSession.objects.filter(user=user).delete()

        # Mark user as offline
        profile = UserProfile.objects.get(user=user)
        profile.is_online = False
        profile.save()

        logger.info(f"{user.username} marked offline successfully")
    except UserProfile.DoesNotExist:
        logger.warning(f"No UserProfile found for {user.username}")

@receiver(user_signed_up)
def handle_social_signup(request, user, **kwargs):
    print("🔥 user_signed_up signal triggered for:", user.username)

    profile, created = UserProfile.objects.get_or_create(user=user)
    profile.is_online = True
    profile.is_approved = False  # ✅ Must be manually approved
    profile.save()
    print("✅ Profile saved with approval = False")

    login(request, user, backend='allauth.account.auth_backends.AuthenticationBackend')
    print("🔓 login() called")

    try:
        send_mail(
            subject=f"🆕 New Google Signup (Pending Approval): {user.username}",
            message=f"A new user has signed up and requires approval.\n\nUsername: {user.username}\nEmail: {user.email}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[admin_email for _, admin_email in settings.ADMINS],
            fail_silently=True,
        )
    except Exception as e:
        print("❌ Failed to send mail:", e)

@receiver(allauth_logged_in)
def handle_google_logged_in(request, user, **kwargs):
    print("🔥 allauth user_logged_in triggered:", user.username)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.is_online = True
    # ✅ Do NOT override is_approved — preserve it!
    profile.save()
    print("✅ Profile marked online without changing approval")
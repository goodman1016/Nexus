from allauth.account.adapter import DefaultAccountAdapter
import re
import uuid

class CustomAccountAdapter(DefaultAccountAdapter):
    def populate_username(self, request, user):
        # Skip for social logins — let CustomSocialSignupForm handle it
        if hasattr(request, "sociallogin"):
            print("⚠️ Skipping populate_username due to social login")
            return

        if user.username:
            return

        first = user.first_name or ''
        last = user.last_name or ''
        base = (first + last).replace(" ", "").lower()

        if not base:
            base = f"user{uuid.uuid4().hex[:6]}"

        base = re.sub(r'[^a-zA-Z0-9_]', '', base)
        unique_username = self.generate_unique_username([base])
        print("✅ Populating unique username:", unique_username)

        user.username = unique_username

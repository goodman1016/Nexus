from django import forms
from .models import JobApplication, UserProfile
from django.contrib.auth.models import User
from allauth.socialaccount.forms import SignupForm as SocialSignupForm
from django.contrib.auth import login
import uuid

# === Job Application Form ===
class JobApplicationForm(forms.ModelForm):
    class Meta:
        model = JobApplication
        fields = ['company_name', 'job_title', 'job_url', 'notes', 'status']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['job_url'].required = False
        self.fields['notes'].required = False

# === User Profile Extension Form ===
class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['profile_picture', 'phone_number']
        widgets = {
            'phone_number': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-md p-2 shadow-sm focus:ring focus:ring-blue-300'
            }),
            'profile_picture': forms.ClearableFileInput(attrs={
                'class': 'w-full border border-gray-300 rounded-md p-2 bg-gray-50 shadow-sm'
            })
        }

# === Custom Social Signup Form ===
class CustomSocialSignupForm(SocialSignupForm):
    def save(self, request):
        print("✅ CustomSocialSignupForm.save() called")
        user = super().save(request)

        try:
            sociallogin = self.sociallogin
            extra_data = sociallogin.account.extra_data
            print("✅ extra_data:", extra_data)

            # Extract base name from Google profile
            first = extra_data.get("given_name") or extra_data.get("first_name") or ""
            last = extra_data.get("family_name") or extra_data.get("last_name") or ""
            base_username = (first + last).replace(" ", "").lower()

            # Fallback if no name is available
            if not base_username:
                base_username = f"user{uuid.uuid4().hex[:6]}"

            # Guarantee uniqueness
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            print("✅ Final unique username:", username)
            user.username = username
            user.save()

        except Exception as e:
            print("❌ Error in CustomSocialSignupForm:", str(e))

        # ✅ Always login with backend explicitly
        login(request, user, backend='allauth.account.auth_backends.AuthenticationBackend')

        return user
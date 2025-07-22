from django.contrib.auth.models import User
from django.db import models
from django.utils.timezone import now
import os
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

class ApplicationStatus(models.Model):
    name = models.CharField(max_length=100, unique=True)
    rank = models.PositiveIntegerField(default=0)
    score = models.FloatField(default=0.0)

    class Meta:
        ordering = ['rank']  # This will sort by rank in queries

    def __str__(self):
        return self.name

# -------------------------------
# JobApplication Model
# -------------------------------
class JobApplication(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('pending', 'Pending'),
        ('paid', 'Paid'),
    ]

    company_name = models.CharField(max_length=255)
    job_title = models.CharField(max_length=255)
    job_url = models.CharField(max_length=1000, blank=True)
    notes = models.TextField(blank=True)
    status = models.ForeignKey(ApplicationStatus, on_delete=models.SET_NULL, null=True, blank=True)
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default='unpaid')
    payment_batch = models.ForeignKey('PaymentBatch', null=True, blank=True, on_delete=models.SET_NULL, related_name='job_applications')
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    email = models.EmailField(blank=True, null=True)

    def __str__(self):
        return f"{self.job_title} @ {self.company_name}"

    @property
    def calculated_score(self):
        from .models import CallerRequest, InterviewProposal

        caller_scores = CallerRequest.objects.filter(application=self, approved=True)
        interview_scores = InterviewProposal.objects.filter(application=self, approved=True)

        total = sum(r.proposed_status.score for r in caller_scores)
        total += sum(i.proposed_status.score for i in interview_scores)
        return total

    @property
    def display_status(self):
        from .models import CallerRequest, InterviewProposal

        # Fetch all approved status proposals
        caller_statuses = CallerRequest.objects.filter(application=self, approved=True).select_related('proposed_status')
        interview_statuses = InterviewProposal.objects.filter(application=self, approved=True).select_related('proposed_status')

        all_statuses = list(caller_statuses) + list(interview_statuses)

        if not all_statuses:
            return self.status  # fallback to default status if no approvals

        # Find the proposed_status with highest rank
        highest = max(
            (req.proposed_status for req in all_statuses),
            key=lambda s: s.rank,
            default=self.status
        )

        return highest

# -------------------------------
# UserProfile Model
# -------------------------------
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    is_online = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username


# -------------------------------
# UserSession Model (Optional)
# -------------------------------
class UserSession(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    session_key = models.CharField(max_length=40)


# -------------------------------
# CallerRequest Model
# -------------------------------
class CallerRequest(models.Model):
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE)
    caller = models.ForeignKey(User, on_delete=models.CASCADE)
    proposed_status = models.ForeignKey(ApplicationStatus, on_delete=models.CASCADE)
    comment = models.TextField(blank=True)
    approved = models.BooleanField(null=True)  # None = pending
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.application.job_title} – {self.proposed_status} by {self.caller.username}"
    
    def save(self, *args, **kwargs):
        if self.approved is True:
            if not self.approved_at:
                self.approved_at = now()
            self.rejected_at = None

            # ✅ Automatically update application status
            if self.application.status != self.proposed_status:
                self.application.status = self.proposed_status
                self.application.save()

        elif self.approved is False:
            if not self.rejected_at:
                self.rejected_at = now()
            self.approved_at = None
        else:  # None means "Pending"
            self.approved_at = None
            self.rejected_at = None

        super().save(*args, **kwargs)

class InterviewProposal(models.Model):
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE)
    caller = models.ForeignKey(User, on_delete=models.CASCADE)
    proposed_status = models.ForeignKey(ApplicationStatus, on_delete=models.CASCADE)
    approved = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.application} - {self.proposed_status.name} by {self.caller.username}"

    def save(self, *args, **kwargs):
        if self.approved:
            if not self.approved_at:
                self.approved_at = now()

            # ✅ Automatically update application status
            if self.application.status != self.proposed_status:
                self.application.status = self.proposed_status
                self.application.save()

        super().save(*args, **kwargs)

class PaymentBatch(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    cutoff_date = models.DateField()
    total_score = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed = models.BooleanField(default=False)

    def __str__(self):
        return f"Payment for {self.user.username} until {self.cutoff_date}"

@receiver(pre_delete, sender=PaymentBatch)
def reset_application_payment_status(sender, instance, **kwargs):
    instance.job_applications.update(
        payment_status='unpaid',
        payment_batch=None
    )
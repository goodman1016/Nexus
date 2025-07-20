from django.contrib import admin
from .models import UserProfile, JobApplication, CallerRequest, ApplicationStatus
from django.utils.html import format_html
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.timezone import now
from .models import PaymentBatch
from django.utils.safestring import mark_safe
from django.urls import reverse

# Inline for Job Applications in UserAdmin
class JobApplicationInline(admin.TabularInline):
    model = JobApplication
    extra = 0
    max_num = 20  # Limits to showing 20 records in the inline form
    readonly_fields = ('job_title', 'company_name', 'status', 'created_at')
    fk_name = 'user'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by('-created_at')[:20]  # Show only the latest 20 applications

# Inline for UserProfile
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False

# Customized UserAdmin
# Customized UserAdmin
class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline, JobApplicationInline]
    list_display = (
        'username',
        'email',
        'first_name',
        'last_name',
        'is_staff',
        'is_superuser',
        'is_active',
        'get_groups',
        'get_is_online',
        'get_is_approved',
        'view_all_applications_link',
    )
    
    def view_all_applications_link(self, obj):
        url = reverse("admin:jobs_jobapplication_changelist") + f"?user__id__exact={obj.id}"
        return mark_safe(f'<a href="{url}" target="_blank">🔍 View All</a>')

    view_all_applications_link.short_description = "Applications"
        
    def get_is_online(self, obj):
        try:
            return obj.userprofile.is_online
        except UserProfile.DoesNotExist:
            return False
    get_is_online.short_description = 'Online'
    get_is_online.boolean = True

    def get_is_approved(self, obj):
        try:
            return obj.userprofile.is_approved
        except UserProfile.DoesNotExist:
            return False
    get_is_approved.short_description = 'Approved'
    get_is_approved.boolean = True

    def get_groups(self, obj):
        return ", ".join([group.name for group in obj.groups.all()])
    get_groups.short_description = 'Groups'

admin.site.unregister(User)
admin.site.register(User, UserAdmin)


# -------------------------------
# JobApplication Admin
# -------------------------------
@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Job Info", {
            "fields": ("job_title", "company_name", "job_url", "status"),
            "classes": ("wide",)
        }),
        ("User Info", {
            "fields": ("user", "email"),
            "classes": ("collapse",)
        }),
        ("Timestamps & Score", {
            "fields": ("created_at", "get_score"),
            "classes": ("collapse",)
        }),
    )

    list_display = ('job_title', 'company_name', 'colored_status', 'user', 'created_at', 'get_score', 'payment_status', 'payment_batch')
    list_filter = ('status', 'created_at')
    search_fields = ('job_title', 'company_name', 'user__username')
    readonly_fields = ('created_at', 'get_score')  # use custom score field here
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_per_page = 20

    def colored_status(self, obj):
        color_map = {
            "applied": "blue",
            "recruiter call": "purple",
            "hr interview": "orange",
            "technical interview": "teal",
            "offer": "green",
            "rejected": "red"
        }
        status_obj = obj.display_status
        if not status_obj:
            return "—"

        color = color_map.get(status_obj.name.lower(), "gray")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            status_obj.name
        )

    colored_status.short_description = "Status"

    def get_score(self, obj):
        score = obj.calculated_score
        return score if score > 0 else 1.0

    get_score.short_description = "Calculated Score"
    get_score.admin_order_field = 'status__score'

    actions = ['create_payment_batch']

    @admin.action(description="💰 Create PaymentBatch for selected unpaid applications")
    def create_payment_batch(self, request, queryset):
        from .models import PaymentBatch
        from django.utils.timezone import now

        users = queryset.values_list('user', flat=True).distinct()

        for user_id in users:
            user_jobs = queryset.filter(user__id=user_id, payment_status='unpaid')
            if not user_jobs.exists():
                continue

            total_score = sum(job.calculated_score if job.calculated_score > 0 else 1.0 for job in user_jobs)

            batch = PaymentBatch.objects.create(
                user=user_jobs.first().user,
                cutoff_date=now().date(),
                total_score=total_score,
                confirmed=False
            )

            user_jobs.update(payment_status='paid', payment_batch=batch)

        self.message_user(request, "✅ Payment batches created and applications marked as paid.")

# -------------------------------
# CallerRequest Admin
# -------------------------------

@admin.register(CallerRequest)
class CallerRequestAdmin(admin.ModelAdmin):
    list_display = ('application_display', 'caller', 'proposed_status', 'approved', 'approved_at', 'rejected_at')
    list_filter = ('approved', 'proposed_status')
    search_fields = ('caller__username', 'application__job_title')
    date_hierarchy = 'approved_at'
    actions = ['approve_selected', 'reject_selected']  # ✅ Add actions here

    def application_display(self, obj):
        if obj.application:
            job_title = obj.application.job_title.replace('@', ' at ')
            company = obj.application.company_name.replace('@', ' at ')
            return f"{job_title} at {company}"
        return "-"
    application_display.short_description = 'Application'

    def save_model(self, request, obj, form, change):
        obj.save()

    # ✅ Bulk approve action
    @admin.action(description="✅ Approve selected caller requests")
    def approve_selected(self, request, queryset):
        for obj in queryset:
            obj.approved = True
            obj.save()

    # ✅ Bulk reject action
    @admin.action(description="❌ Reject selected caller requests")
    def reject_selected(self, request, queryset):
        for obj in queryset:
            obj.approved = False
            obj.save()

@admin.register(ApplicationStatus)
class ApplicationStatusAdmin(admin.ModelAdmin):
    list_display = ('name', 'rank', 'score')
    list_editable = ('rank', 'score')
    
@admin.register(PaymentBatch)
class PaymentBatchAdmin(admin.ModelAdmin):
    list_display = ('user', 'cutoff_date', 'total_score', 'confirmed', 'created_at')
    list_filter = ('confirmed',)
    list_editable = ('confirmed',)
    ordering = ('-cutoff_date', 'user')
    search_fields = ('user__username',)

    def delete_model(self, request, obj):
        # Reset related applications
        related_apps = obj.job_applications.all()
        related_apps.update(payment_status='unpaid', payment_batch=None)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        # Reset related applications for bulk delete
        for obj in queryset:
            obj.job_applications.update(payment_status='unpaid', payment_batch=None)
        super().delete_queryset(request, queryset)

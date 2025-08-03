from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from .models import JobApplication
from django.utils.timezone import make_aware, now, timedelta
from datetime import datetime
from django.db.models import Count
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.auth import login, authenticate
from .models import UserProfile
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.db.models.functions import TruncDate
from collections import defaultdict
from django.core.mail import mail_admins
from django.db import IntegrityError
from django import forms
from .forms import UserProfileForm
from django.contrib.admin.views.decorators import staff_member_required
from .models import CallerRequest
from django.contrib.auth.models import Group
from django.utils import timezone
from django.core.files.base import File
from django.core.files import File as DjangoFile
from .models import InterviewProposal
from django.db.models import Q
from django.template.loader import render_to_string
from .models import ApplicationStatus
from django.shortcuts import get_object_or_404
from urllib.parse import unquote_plus

from django.contrib.auth import logout

import subprocess
import os
import json

from django.db.models import Prefetch

def check_approval(request):
    if not request.user.is_staff and not request.user.userprofile.is_approved:
        return HttpResponseForbidden("⚠️ Your account is pending admin approval.")

current_dir = os.path.dirname(os.path.abspath(__file__))

def convert_doc_to_pdf(input_path, output_dir):
    libreoffice_path = r"C:\Program Files\LibreOffice\program\soffice.exe"  # Windows full path

    try:
        subprocess.run([
            libreoffice_path,
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', output_dir,
            input_path
        ], check=True)
    except subprocess.CalledProcessError as e:
        return None

    pdf_name = os.path.splitext(os.path.basename(input_path))[0] + '.pdf'
    return os.path.join(output_dir, pdf_name)

# === Group Helpers ===
def is_admin(user):
    return user.groups.filter(name='admins').exists()

def is_caller(user):
    return user.groups.filter(name='callers').exists()

def is_contributor(user):
    return user.groups.filter(name='contributors').exists()

@login_required
def home(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    return render(request, 'jobs/home.html')

def applications(request):
    if request.method == 'GET':
        selected_user_id = request.GET.get('user_id')

        search_title = request.GET.get('job_title', '').strip()
        search_company = request.GET.get('company_name', '').strip()
        search_status_raw = unquote_plus(request.GET.get('status', '').strip())
        search_status = search_status_raw.lower()

        base_queryset = JobApplication.objects.select_related('user').prefetch_related(
            Prefetch('callerrequest_set', queryset=CallerRequest.objects.filter(approved=True)),
            Prefetch('interviewproposal_set', queryset=InterviewProposal.objects.filter(approved=True)),
        ).annotate(
            approved_call_count=Count('callerrequest', filter=Q(callerrequest__approved=True))
        )

        if request.user.is_staff or is_caller(request.user):
            if selected_user_id:
                base_queryset = base_queryset.filter(user__id=selected_user_id)
        else:
            base_queryset = base_queryset.filter(user=request.user)

        if search_title:
            base_queryset = base_queryset.filter(job_title__icontains=search_title)
        if search_company:
            base_queryset = base_queryset.filter(company_name__icontains=search_company)

        total_count = base_queryset.count()

        try:
            page_size = int(request.GET.get('page_size', 10))
        except ValueError:
            page_size = 10

        paginator = Paginator(base_queryset, page_size)

        try:
            page_number = int(request.GET.get('page', 1))
        except ValueError:
            page_number = 1

        if page_number < 1:
            page_number = 1
        elif page_number > paginator.num_pages:
            page_number = paginator.num_pages

        page_obj = paginator.page(page_number)
        jobs = list(page_obj.object_list)

        final_jobs = []
        for job in jobs:
            approved_reqs = job.callerrequest_set.all()
            approved_proposals = job.interviewproposal_set.all()

            score_breakdown = defaultdict(int)
            total_score = 0

            for req in approved_reqs:
                if req.proposed_status:
                    label = req.proposed_status.name
                    score = req.proposed_status.score
                    score_breakdown[label] += 1
                    total_score += score

            for prop in approved_proposals:
                if prop.proposed_status:
                    label = prop.proposed_status.name
                    score = prop.proposed_status.score
                    score_breakdown[label] += 1
                    total_score += score

            all_approved = list(approved_reqs) + list(approved_proposals)
            top_ranked = sorted(
                (x for x in all_approved if x.proposed_status),
                key=lambda x: x.proposed_status.rank,
                reverse=True
            )

            job._display_status = top_ranked[0].proposed_status if top_ranked else job.status
            job.total_score = total_score if total_score > 0 else 1.0
            job.score_tooltip = ", ".join(f"{k}: {v}" for k, v in score_breakdown.items()) if score_breakdown else "Applied"

            job_status_name = job._display_status.name.strip() if job._display_status else ''
            approved_status_names = {s.proposed_status.name.strip() for s in all_approved if s.proposed_status}
            job_status_name_lower = job_status_name.lower()
            approved_status_names_lower = {s.lower() for s in approved_status_names}

            if search_status in ('', 'all') or search_status == job_status_name_lower or search_status in approved_status_names_lower:
                final_jobs.append(job)

        jobs = final_jobs

        sort_field = request.GET.get('sort', '')
        sort_order = request.GET.get('order', 'asc')
        valid_fields = ['job_title', 'company_name', 'job_url', 'created_at', 'status']
        if sort_field in valid_fields:
            reverse = sort_order == 'desc'
            if sort_field == 'status':
                jobs.sort(key=lambda x: getattr(x._display_status, 'rank', 0), reverse=reverse)
            else:
                jobs.sort(key=lambda x: getattr(x, sort_field, ''), reverse=reverse)
        else:
            jobs.sort(key=lambda x: x.created_at, reverse=True)

        # Accurate user_score calculation
        if request.user.is_staff:
            user_score = None
        else:
            user_jobs = JobApplication.objects.filter(user=request.user, payment_status="unpaid").select_related('user')
            user_score = 0
            for job in user_jobs:
                approved_reqs = CallerRequest.objects.filter(application=job, approved=True)
                approved_props = InterviewProposal.objects.filter(application=job, approved=True)
                total_score = 0
                for req in approved_reqs:
                    if req.proposed_status:
                        total_score += req.proposed_status.score
                for prop in approved_props:
                    if prop.proposed_status:
                        total_score += prop.proposed_status.score
                user_score += total_score if total_score > 0 else 1.0

        all_users = User.objects.all() if request.user.is_staff else None
        is_contributor_flag = request.user.groups.filter(name='contributors').exists()
        is_admin = request.user.groups.filter(name='admins').exists() or request.user.is_superuser
        interview_statuses = ApplicationStatus.objects.exclude(name__iexact="Applied").order_by('rank')
        all_statuses = ApplicationStatus.objects.order_by('rank')

        return render(request, 'jobs/applications.html', {
            'page_obj': page_obj,
            'page_size': page_size,
            'user_score': user_score,
            'showing_mine': request.GET.get("mine") == "1",
            'selected_user_id': int(selected_user_id) if selected_user_id else '',
            'is_admin': request.user.is_superuser,
            'all_users': all_users,
            'is_caller': is_caller(request.user),
            'is_contributor': is_contributor_flag,
            'is_admin': is_admin,
            'all_statuses': all_statuses,
            'interview_statuses': interview_statuses,
            'jobs': jobs,  # filtered and decorated jobs
            'total_pages': paginator.num_pages,
            'total_count': total_count,
        })
        
    if request.method == 'POST':
        job_id = request.POST.get('job_id')
        
        # Use top-ranked ApplicationStatus if status not posted
        status_obj = None
        status_id = request.POST.get('status')
        if status_id:
            try:
                status_obj = ApplicationStatus.objects.get(id=status_id)
            except ApplicationStatus.DoesNotExist:
                pass

        if not status_obj:
            status_obj = ApplicationStatus.objects.order_by('rank').first()
            if not status_obj:
                return JsonResponse({'status': 'error', 'message': 'No status available. Please ask admin to create at least one status.'}, status=500)

        if job_id:
            try:
                job = JobApplication.objects.get(id=job_id)
                job.status = status_obj
                job.save()

                caller_requests = CallerRequest.objects.filter(application=job)

                for cr in caller_requests:
                    approved_value = request.POST.get('approved')
                    if approved_value == 'unknown':
                        cr.approved = None
                        cr.approved_at = None
                        cr.rejected_at = None
                    elif approved_value == 'yes':
                        cr.approved = True
                        cr.approved_at = timezone.now()
                        cr.rejected_at = None
                    elif approved_value == 'no':
                        cr.approved = False
                        cr.rejected_at = timezone.now()
                        cr.approved_at = None

                    cr.save()

                return JsonResponse({
                    'status': 'success',
                    'message': 'Job status updated successfully',
                    'job': {
                        'id': job.id,
                        'job_title': job.job_title,
                        'company_name': job.company_name,
                        'job_url': job.job_url,
                        'status': job.status.name if job.status else '',
                        'calculated_score': job.calculated_score,
                    },
                    'user_score': sum(app.calculated_score for app in JobApplication.objects.filter(user=request.user))
                })
            except JobApplication.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'Job not found'}, status=404)

        # New job creation
        job_title = request.POST.get('job_title')
        company_name = request.POST.get('company_name')
        job_url = request.POST.get('job_url')
        notes = request.POST.get('notes', '')
        real_email = request.user.email

        if not job_title or not company_name or not job_url:
            return JsonResponse({'status': 'error', 'message': 'All fields are required'}, status=400)

        job = JobApplication.objects.create(
            job_title=job_title,
            company_name=company_name,
            job_url=job_url,
            status=status_obj,
            notes=notes,
            user=request.user,
            email=real_email
        )

        return JsonResponse({
            'status': 'success',
            'message': 'Job added successfully',
            'job': {
                'id': job.id,
                'job_title': job.job_title,
                'company_name': job.company_name,
                'job_url': job.job_url,
                'notes': job.notes,
                'status': job.status.name if job.status else None,
                'created_at': job.created_at.astimezone().isoformat(),
                'user': request.user.username,
                'email': real_email,
                'calculated_score': job.calculated_score,
            },
            'is_staff': request.user.is_staff
        })

@login_required
def delete_job(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    if request.method == 'POST':
        job = get_object_or_404(JobApplication, id=request.POST.get('job_id'))
        job.delete()
        return JsonResponse({'status': 'success', 'message': 'Job deleted successfully'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})

@login_required
def application_heatmap_data(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    year = int(request.GET.get('year', datetime.now().year))
    month = int(request.GET.get('month', datetime.now().month))
    start_date = make_aware(datetime(year, month, 1))
    end_date = make_aware(datetime(year + (month // 12), ((month % 12) + 1), 1))
    data = JobApplication.objects.filter(
        created_at__gte=start_date,
        created_at__lt=end_date
    ).extra(select={'day': "DATE(created_at)"}).values('day').annotate(count=Count('id')).order_by('day')

    return JsonResponse([
        {"date": d["day"], "value": d["count"]}
        for d in data
    ], safe=False)

from django.utils.timezone import now
from datetime import timedelta

@login_required
def get_job_status_counts(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check

    user_id = request.GET.get("user_id") or None

    # Determine target_user
    if request.user.is_superuser and user_id:
        target_user = get_object_or_404(User, id=user_id)
    elif not request.user.is_superuser:
        target_user = request.user
    else:
        target_user = None  # All users

    # Base queryset
    queryset = JobApplication.objects.only(
        'id', 'user_id', 'created_at', 'status', 'job_title', 'company_name'
    ).select_related('status')

    if target_user:
        queryset = queryset.filter(user=target_user)

    queryset = queryset.filter(created_at__gte=now() - timedelta(days=90))

    # Prefetch related CallerRequests (approved with proposed_status)
    queryset = queryset.prefetch_related(
        Prefetch(
            'callerrequest_set',
            queryset=CallerRequest.objects.filter(
                approved=True,
                proposed_status__isnull=False
            ).select_related('proposed_status'),
            to_attr='approved_requests'
        )
    )

    counts = {'applied': 0, 'interview': 0, 'offer': 0, 'rejected': 0}

    # Build lookup for ranks
    rank_map = {
        status.id: status.rank for status in ApplicationStatus.objects.all()
    }

    for job in queryset:
        approved_reqs = job.approved_requests  # Now attached by prefetch

        if approved_reqs:
            top_req = sorted(
                approved_reqs,
                key=lambda r: rank_map.get(r.proposed_status.id, 0),
                reverse=True
            )[0]
            status_name = top_req.proposed_status.name.lower()
        elif job.status:
            status_name = job.status.name.lower()
        else:
            status_name = "applied"  # fallback

        # Map to one of four labels
        if "applied" in status_name:
            counts["applied"] += 1
        elif "offer" in status_name:
            counts["offer"] += 1
        elif "reject" in status_name:
            counts["rejected"] += 1
        else:
            counts["interview"] += 1

    return JsonResponse(counts)

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(required=True)
    last_name = forms.CharField(required=True)

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "password1", "password2")
        
def register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('home')
    else:
        form = CustomUserCreationForm()
    return render(request, 'registration/register.html', {'form': form})

@login_required
def profile_view(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check

    user = request.user
    user_jobs = JobApplication.objects.filter(user=user, payment_status="unpaid")
    user_score = 0

    for job in user_jobs:
        approved_reqs = CallerRequest.objects.filter(application=job, approved=True)
        total = 0
        for req in approved_reqs:
            if req.proposed_status:
                total += req.proposed_status.score
        user_score += total if total > 0 else 1.0

    return render(request, 'jobs/profile.html', {
        'user': user,
        'user_score': user_score,
    })

@login_required
def edit_profile_view(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile_form = UserProfileForm(request.POST or None, request.FILES or None, instance=profile)

    if request.method == 'POST':
        if profile_form.is_valid():
            profile_form.save()
            return redirect('profile')

    return render(request, 'jobs/edit_profile.html', {
        'profile_form': profile_form,
    })

@login_required
def settings_view(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    return render(request, 'jobs/settings.html')


@login_required
def skill_matcher_view(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    return render(request, 'jobs/skill_matcher.html')

@login_required
def user_status_view(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    if not request.user.is_superuser:
        return HttpResponseForbidden("You are not authorized to view this page.")

    profiles = UserProfile.objects.select_related('user')
    return render(request, 'jobs/user_status.html', {'profiles': profiles})

class CustomLoginView(LoginView):
    def get(self, request, *args, **kwargs):
        request.session.pop('login_error', None)
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)

        if request.session.get('login_error'):
            messages.error(request, request.session.pop('login_error'))
            return redirect('login')

        return response
    
@require_POST
@login_required
def update_job_fields(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    job_id = request.POST.get('job_id')
    title = request.POST.get('job_title')
    company = request.POST.get('company_name')
    url = request.POST.get('job_url')

    try:
        job = JobApplication.objects.get(id=job_id)

        user_info = f"[Update Attempt] User: {request.user.username} (Staff: {request.user.is_staff}) → Job Owner: {job.user.username}"

        # Allow both the owner and staff to edit
        if request.user != job.user and not request.user.is_staff:
            print(user_info + "   ❌ Result: Permission denied")
            return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)

        job.job_title = title
        job.company_name = company
        job.job_url = url
        job.save()

        print(user_info + "   ✅ Result: Success")
        return JsonResponse({'status': 'success'})

    except JobApplication.DoesNotExist:
        print(f"[Update Attempt] User: {request.user.username} → ❌ Result: Job ID {job_id} not found")
        return JsonResponse({'status': 'error', 'message': 'Job not found'}, status=404)

@require_POST
@login_required
def update_job_status(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    job_id = request.POST.get('job_id')
    new_status = request.POST.get('status')

    try:
        job = JobApplication.objects.get(id=job_id)

        # Only allow owner or admin
        if request.user != job.user and not request.user.is_staff:
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

        job.status = new_status
        job.save()
        return JsonResponse({'success': True})
    
    except JobApplication.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Job not found'}, status=404)

@login_required
def application_charts(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check

    user_id = request.GET.get("user_id")
    selected_user_id = user_id or ""  # Set default for template

    # Determine which user's data to show
    if request.user.is_superuser:
        if user_id:
            target_user = get_object_or_404(User, id=user_id)
            queryset = JobApplication.objects.filter(user=target_user)
        else:
            queryset = JobApplication.objects.only('id', 'user_id', 'created_at', 'status', 'job_title', 'company_name').select_related('status')  # Show all users if no specific ID
    else:
        queryset = JobApplication.objects.filter(user=request.user)
        selected_user_id = str(request.user.id)
        
    queryset = queryset.filter(created_at__gte=now() - timedelta(days=90))

    total_applications = queryset.count()
    total_interviews = queryset.filter(status__name__icontains="Interview").count()
    total_offers = queryset.filter(status__name__iexact="Offer").count()

    recent_jobs = list(
        queryset.order_by('-created_at')[:5].values(
            'job_title', 'company_name', 'status', 'created_at'
        )
    )

    return render(request, 'jobs/charts.html', {
        'recent_jobs': json.dumps(recent_jobs, default=str),
        'is_admin': request.user.is_superuser,
        'users': User.objects.all() if request.user.is_superuser else [],
        'selected_user_id': selected_user_id,
        'total_applications': total_applications,
        'total_interviews': total_interviews,
        'total_offers': total_offers,
    })

@require_POST
@login_required
def update_payment_status(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    if not is_admin(request.user):
        return HttpResponseForbidden("Only admin can update payment status.")

    job_id = request.POST.get("job_id")
    new_status = request.POST.get("payment_status")

    try:
        job = JobApplication.objects.get(id=job_id)
        job.payment_status = new_status
        job.save()
        return JsonResponse({"success": True})
    except JobApplication.DoesNotExist:
        return JsonResponse({"success": False, "error": "Job not found"}, status=404)
    
@login_required
def get_applications_json(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    user_id = request.GET.get("user_id") or None

    if request.user.is_superuser and user_id:
        target_user = get_object_or_404(User, id=user_id)
    elif not request.user.is_superuser:
        target_user = request.user
    else:
        target_user = None  # All users (admin)

    queryset = JobApplication.objects.only('id', 'user_id', 'created_at', 'status', 'job_title', 'company_name').select_related('status')
    if target_user:
        queryset = queryset.filter(user=target_user)
    
    queryset = queryset.filter(created_at__gte=now() - timedelta(days=90))
    jobs = (
        queryset
        .annotate(day=TruncDate('created_at'))
        .values('day', 'status')
        .annotate(count=Count('id'))
        .order_by('day')
    )

    from collections import defaultdict
    grouped = defaultdict(lambda: defaultdict(int))
    for job in jobs:
        grouped[job["day"]][job["status"]] += job["count"]

    events = []
    for day, status_dict in grouped.items():
        total = sum(status_dict.values())
        breakdown = ", ".join(f"{v} {k}" for k, v in status_dict.items())
        events.append({
            "title": str(total),
            "count": total,
            "status_breakdown": breakdown,
            "start": day.strftime("%Y-%m-%d")
        })

    return JsonResponse(events, safe=False)

def custom_403_view(request, exception=None):
    return render(request, '403.html', status=403)

@require_POST
@login_required
def propose_interview(request, job_id):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    job = get_object_or_404(JobApplication, id=job_id)

    # Only non-admins can propose
    if request.user.is_staff:
        return HttpResponseForbidden("Admins cannot propose interview requests.")

    comment = request.POST.get("comment", "").strip()
    proposed_status = request.POST.get("status", "Recruiter Call")

    # Prevent duplicate requests for same job by same caller if not reviewed
    existing = CallerRequest.objects.filter(application=job, caller=request.user, approved=None)
    if existing.exists():
        messages.warning(request, "You already proposed an interview for this application.")
        return redirect("applications")

    CallerRequest.objects.create(
        application=job,
        caller=request.user,
        proposed_status=proposed_status,
        comment=comment,
        approved=None
    )

    messages.success(request, "Interview proposal submitted successfully.")
    return redirect("applications")

@require_POST
@login_required
def propose_interview_global(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    if not request.user.is_staff and not is_caller(request.user):
        return HttpResponseForbidden("You are not allowed to propose interviews.")

    job_id = request.POST.get("application_id")
    status_id = request.POST.get("status")
    comment = request.POST.get("comment", "").strip()

    job = get_object_or_404(JobApplication, id=job_id)
    proposed_status = get_object_or_404(ApplicationStatus, id=status_id)

    CallerRequest.objects.create(
        application=job,
        caller=request.user,
        proposed_status=proposed_status,
        comment=comment,
        approved=None
    )

    messages.success(request, "Interview proposed successfully.")
    return redirect("applications")

def logout_view(request):
    if request.user.is_authenticated:
        try:
            profile = request.user.userprofile
            profile.is_online = False
            profile.save()
        except UserProfile.DoesNotExist:
            pass

    logout(request)
    list(messages.get_messages(request))  # Clear all previous messages
    messages.info(request, "You have been logged out.")
    return redirect('login')

@login_required
def interviews_view(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check

    proposals = CallerRequest.objects.filter(
        caller=request.user
    ).select_related('application')

    # Filters
    status_filter = request.GET.get('filter')
    search_query = request.GET.get('search')

    if status_filter == 'approved':
        proposals = proposals.filter(approved=True)
    elif status_filter == 'rejected':
        proposals = proposals.filter(approved=False)
    elif status_filter == 'pending':
        proposals = proposals.filter(approved=None)

    if search_query:
        proposals = proposals.filter(
            Q(application__job_title__icontains=search_query) |
            Q(application__company_name__icontains=search_query)
        )
        
    # ✅ Order the queryset to avoid UnorderedObjectListWarning
    proposals = proposals.order_by('-application__created_at')
    
    # Pagination
    page_number = request.GET.get('page', 1)
    paginator = Paginator(proposals, 10)  # 10 items per page
    page_obj = paginator.get_page(page_number)

    # Summary counts
    approved_count = proposals.filter(approved=True).count()
    rejected_count = proposals.filter(approved=False).count()
    pending_count = proposals.filter(approved=None).count()

    # User score
    user_score = 0
    if not request.user.is_staff:
        approved_proposals = CallerRequest.objects.filter(
            caller=request.user,
            approved=True,
            application__payment_status="unpaid"
        ).select_related('proposed_status')

        for req in approved_proposals:
            user_score += req.proposed_status.score if req.proposed_status and req.proposed_status.score is not None else 1.0

    return render(request, 'jobs/interviews_user.html', {
        'page_obj': page_obj,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'pending_count': pending_count,
        'user_score': user_score,
    })
    
@require_POST
@login_required
def update_caller_approval(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    if not is_admin(request.user):
        return HttpResponseForbidden("Only admin can update approval status.")

    proposal_id = request.POST.get("proposal_id")
    approved_value = request.POST.get("approved")

    try:
        proposal = CallerRequest.objects.get(id=proposal_id)

        if approved_value == "yes":
            proposal.approved = True
            proposal.approved_at = timezone.now()
            proposal.rejected_at = None
            proposal.save()

            # Fetch ranked status list dynamically
            INTERVIEW_STAGE_PRIORITY = {
                status.name: status.rank
                for status in ApplicationStatus.objects.all()
            }

            # ✅ Get the highest-ranked approved proposal for this job
            approved_proposals = CallerRequest.objects.filter(
                application=proposal.application,
                approved=True
            )

            ranked = sorted(
                approved_proposals,
                key=lambda p: INTERVIEW_STAGE_PRIORITY.get(p.proposed_status.name if p.proposed_status else "", 0),
                reverse=True
            )

            if ranked:
                top_status = ranked[0].proposed_status
                proposal.application.status = top_status
                proposal.application.save()
                print(f"✅ Updated application #{proposal.application.id} status to: {top_status}")

        elif approved_value == "no":
            proposal.approved = False
            proposal.rejected_at = timezone.now()
            proposal.approved_at = None

        elif approved_value == "unknown":
            proposal.approved = None
            proposal.approved_at = None
            proposal.rejected_at = None

        proposal.save()
        return redirect("interviews")

    except CallerRequest.DoesNotExist:
        return HttpResponseForbidden("Proposal not found.")

from django.template.loader import render_to_string
from django.http import JsonResponse
from django.db.models import Q

@login_required
def live_search_proposals(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check

    search = request.GET.get('search', '').strip()
    filter_status = request.GET.get('filter', '')

    proposals = CallerRequest.objects.filter(caller=request.user).select_related('application')

    if filter_status == 'approved':
        proposals = proposals.filter(approved=True)
    elif filter_status == 'rejected':
        proposals = proposals.filter(approved=False)
    elif filter_status == 'pending':
        proposals = proposals.filter(approved=None)

    if search:
        proposals = proposals.filter(
            Q(application__job_title__icontains=search) |
            Q(application__company_name__icontains=search)
        )

    # Render each proposal row individually using updated row template
    html = "".join(
        render_to_string("jobs/_proposal_row.html", {"proposal": p}, request=request)
        for p in proposals
    )

    return JsonResponse({'html': html})

@login_required
def interview_trend_data(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    queryset = CallerRequest.objects.all()

    if not request.user.is_staff:
        queryset = queryset.filter(caller=request.user)

    queryset = queryset.filter(created_at__gte=now() - timedelta(days=90))
    trend = (
        queryset
        .annotate(date=TruncDate('created_at'))
        .values('date')
        .annotate(count=Count('id'))
        .order_by('date')
    )

    return JsonResponse(list(trend), safe=False)

@login_required
def interview_conversion_data(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    total_applications = JobApplication.objects.count()
    interviewed = CallerRequest.objects.count()
    approved = CallerRequest.objects.filter(approved=True).count()
    rejected = CallerRequest.objects.filter(approved=False).count()

    return JsonResponse({
        'total': total_applications,
        'interviewed': interviewed,
        'approved': approved,
        'rejected': rejected,
    })

@login_required
def interview_charts_view(request):
    approval_check = check_approval(request)
    if approval_check:
        return approval_check
    return render(request, 'jobs/interview_charts.html')

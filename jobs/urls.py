from django.urls import include, path
from .views import logout_view
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('applications', views.applications, name='applications'),
    path('delete_job/', views.delete_job, name='delete_job'),
    path('register/', views.register, name='register'),
    path('heatmap/data/', views.application_heatmap_data, name='application_heatmap_data'),
    path('get_job_status_counts/', views.get_job_status_counts, name='get_job_status_counts'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.edit_profile_view, name='edit_profile'),
    path('settings/', views.settings_view, name='settings'),
    path('skill-matcher/', views.skill_matcher_view, name='skill_matcher'),
    path('user-status/', views.user_status_view, name='user_status'),
    path('update-job-fields/', views.update_job_fields, name='update_job_fields'),
    path('update_job_status/', views.update_job_status, name='update_job_status'),
    path('charts/', views.application_charts, name='application_charts'),
    path('update_payment_status/', views.update_payment_status, name='update_payment_status'),
    path("get_applications_json/", views.get_applications_json, name="get_applications_json"),
    path('interviews/', views.interviews_view, name='interviews_user'),
    path('accounts/', include('allauth.urls')),
    path('propose-interview/<int:job_id>/', views.propose_interview, name='propose_interview'),
    path("propose-interview-global/", views.propose_interview_global, name="propose_interview_global"),
    path("admin/update-caller-approval/", views.update_caller_approval, name="update_caller_approval"),
    path('interviews/live-search/', views.live_search_proposals, name='live_search_proposals'),
    path('interview/trend-data/', views.interview_trend_data, name='interview_trend_data'),
    path('interview/conversion-data/', views.interview_conversion_data, name='interview_conversion_data'),
    path('interviews/interview-c/', views.interview_charts_view, name='interview_charts'),
    path('logout/', logout_view, name='logout'),
]

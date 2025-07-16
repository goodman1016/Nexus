# jobs/templatetags/file_extras.py
import os
from django import template
from django.conf import settings

register = template.Library()

@register.filter
def file_exists(url):
    if not url:
        return False
    try:
        path = url.replace(settings.MEDIA_URL, '')
        full_path = os.path.join(settings.MEDIA_ROOT, path)
        return os.path.exists(full_path)
    except Exception:
        return False

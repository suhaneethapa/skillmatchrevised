import os
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("student/", include("students.urls")),
    path("company/", include("companies.urls")),
    path("admin-panel/", include("admin_panel.urls")),
]

if settings.DEBUG:
    # Public media serving only exposes public assets (e.g. company logos)
    # Private documents (cvs, offer_letters) are strictly protected and served via authenticated views
    logos_dir = settings.MEDIA_ROOT / "logos"
    os.makedirs(logos_dir, exist_ok=True)
    urlpatterns += static(settings.MEDIA_URL + "logos/", document_root=logos_dir)
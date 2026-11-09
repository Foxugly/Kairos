from django.contrib import admin
from django.urls import path

from config.sante import sante

urlpatterns = [
    path("health/", sante, name="sante"),
    path("admin/", admin.site.urls),
]

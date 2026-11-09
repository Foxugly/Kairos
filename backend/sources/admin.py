from django.contrib import admin

from .models import FluxRss, Nouvelle


@admin.register(FluxRss)
class FluxRssAdmin(admin.ModelAdmin):
    list_display = ("nom", "langue", "actif", "dernier_releve", "derniere_erreur")
    list_filter = ("actif", "langue")
    search_fields = ("nom", "url")


@admin.register(Nouvelle)
class NouvelleAdmin(admin.ModelAdmin):
    list_display = ("titre", "flux", "publiee")
    list_filter = ("flux", "valeurs")
    search_fields = ("titre",)
    date_hierarchy = "publiee"
    list_select_related = ("flux",)

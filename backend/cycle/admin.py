import json

from django.contrib import admin
from django.utils.html import format_html

from .models import Cycle


@admin.register(Cycle)
class CycleAdmin(admin.ModelAdmin):
    """Lecture seule : le journal est écrit par la commande `cycle`."""

    list_display = ("debut", "fin", "statut")
    list_filter = ("statut",)
    date_hierarchy = "debut"
    fields = ("debut", "fin", "statut", "journal_lisible")
    readonly_fields = fields

    @admin.display(description="journal")
    def journal_lisible(self, obj):
        return format_html("<pre>{}</pre>", json.dumps(obj.journal, indent=2, ensure_ascii=False))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

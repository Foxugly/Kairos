from django.contrib import admin

from .models import Bareme, RegleCourtage, TauxTob


class RegleCourtageInline(admin.TabularInline):
    model = RegleCourtage
    extra = 0


class TauxTobInline(admin.TabularInline):
    model = TauxTob
    extra = 0


@admin.register(Bareme)
class BaremeAdmin(admin.ModelAdmin):
    list_display = ("nom", "broker", "valide_depuis")
    inlines = [RegleCourtageInline, TauxTobInline]

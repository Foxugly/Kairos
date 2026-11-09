from django.conf import settings
from django.contrib import admin, messages

from .models import Bougie, StatutValeur, TauxChange, Valeur


@admin.register(Valeur)
class ValeurAdmin(admin.ModelAdmin):
    list_display = ("ticker", "nom", "place", "devise", "statut", "imposee")
    list_filter = ("statut", "place")
    search_fields = ("ticker", "nom")
    actions = ["activer"]

    @admin.action(description="Activer les valeurs sélectionnées")
    def activer(self, request, queryset):
        """Active la sélection, sans jamais dépasser `settings.UNIVERS_MAX` (tout ou rien)."""
        a_activer = queryset.exclude(statut=StatutValeur.ACTIVE)
        total = Valeur.objects.actives().count() + a_activer.count()
        if total > settings.UNIVERS_MAX:
            self.message_user(
                request,
                f"Activation refusée : {total} valeurs actives dépasseraient "
                f"l'univers maximal ({settings.UNIVERS_MAX}).",
                messages.ERROR,
            )
            return
        nombre = a_activer.update(statut=StatutValeur.ACTIVE)
        self.message_user(request, f"{nombre} valeur(s) activée(s).", messages.SUCCESS)


@admin.register(Bougie)
class BougieAdmin(admin.ModelAdmin):
    list_display = ("valeur", "intervalle", "debut", "cloture")
    list_filter = ("intervalle",)
    search_fields = ("valeur__ticker",)


@admin.register(TauxChange)
class TauxChangeAdmin(admin.ModelAdmin):
    list_display = ("devise", "instant", "taux")

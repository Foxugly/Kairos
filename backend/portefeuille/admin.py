from django.contrib import admin

from .models import Decision, Ordre, Portefeuille, Position, ResultatBacktest, Valorisation


class LectureSeule(admin.ModelAdmin):
    """Données produites par le cycle : consultables, jamais modifiées à la main."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Portefeuille)
class PortefeuilleAdmin(admin.ModelAdmin):
    list_display = ("nom", "utilise_ia", "capital_initial", "liquidites", "actif")
    readonly_fields = ("liquidites", "indice_quantite", "indice_liquidites", "demarre")


@admin.register(Position)
class PositionAdmin(LectureSeule):
    list_display = ("portefeuille", "valeur", "quantite", "ouverte_le", "fermee_le")
    list_filter = ("portefeuille",)


@admin.register(Ordre)
class OrdreAdmin(LectureSeule):
    list_display = ("instant", "portefeuille", "sens", "valeur", "quantite", "frais_total")
    list_filter = ("portefeuille", "sens")


@admin.register(Decision)
class DecisionAdmin(LectureSeule):
    list_display = ("instant", "portefeuille", "valeur", "action", "pour_le", "executee")
    list_filter = ("portefeuille", "action")


@admin.register(Valorisation)
class ValorisationAdmin(LectureSeule):
    list_display = ("instant", "portefeuille", "total", "indice_total")
    list_filter = ("portefeuille",)


@admin.register(ResultatBacktest)
class ResultatBacktestAdmin(LectureSeule):
    list_display = ("cree", "portefeuille", "debut", "fin", "performance", "performance_indice")
    list_filter = ("portefeuille",)
    exclude = ("courbe",)

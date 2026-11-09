from django.db import models


class StatutCycle(models.TextChoices):
    EN_COURS = "en_cours", "En cours"
    TERMINE = "termine", "Terminé"
    EN_ERREUR = "en_erreur", "En erreur"
    ABANDONNE = "abandonne", "Abandonné"


class Cycle(models.Model):
    """Une exécution de la collecte ; `journal` : {nom_etape: résultat ou {"erreur": message}}."""

    debut = models.DateTimeField()
    fin = models.DateTimeField(null=True, blank=True)
    statut = models.CharField(max_length=10, choices=StatutCycle.choices, default=StatutCycle.EN_COURS)
    journal = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-debut"]

    def __str__(self):
        return f"Cycle {self.debut:%Y-%m-%d %H:%M} ({self.statut})"


class Verrou(models.Model):
    """Ligne unique (pk=1, créée par migration) sur laquelle on prend `select_for_update`.

    Un verrou sur « les cycles en cours » ne verrouillerait rien quand il n'y en a aucun :
    on sérialise donc le contrôle + la création sur une ligne qui existe toujours.
    """

    class Meta:
        verbose_name_plural = "verrous"

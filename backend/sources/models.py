from django.db import models

from marche.models import Valeur


class Langue(models.TextChoices):
    FR = "fr", "Français"
    EN = "en", "Anglais"


class FluxRss(models.Model):
    """Flux RSS/Atom public, relevé à chaque cycle."""

    nom = models.CharField(max_length=100)
    url = models.URLField(max_length=1000, unique=True)
    langue = models.CharField(max_length=2, choices=Langue.choices)
    actif = models.BooleanField(default=True)
    dernier_releve = models.DateTimeField(null=True, blank=True)  # dernier relevé réussi
    derniere_erreur = models.TextField(blank=True)  # vide si le dernier relevé est passé

    class Meta:
        ordering = ["nom"]
        verbose_name = "flux RSS"
        verbose_name_plural = "flux RSS"

    def __str__(self):
        return self.nom


class Nouvelle(models.Model):
    url = models.URLField(max_length=1000, unique=True)
    # sha256 du titre normalisé : la même dépêche reprise par deux flux n'est gardée qu'une fois.
    empreinte = models.CharField(max_length=64, unique=True)
    titre = models.TextField()
    resume = models.TextField(blank=True)
    publiee = models.DateTimeField()  # UTC
    flux = models.ForeignKey(FluxRss, on_delete=models.CASCADE, related_name="nouvelles")
    valeurs = models.ManyToManyField(Valeur, blank=True, related_name="nouvelles")
    recue = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-publiee"]

    def __str__(self):
        return self.titre[:80]

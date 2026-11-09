from django.db import models


class Place(models.TextChoices):
    NASDAQ = "NASDAQ", "Nasdaq"
    NYSE = "NYSE", "NYSE"
    XPAR = "XPAR", "Paris"
    XAMS = "XAMS", "Amsterdam"
    XBRU = "XBRU", "Bruxelles"
    XETR = "XETR", "Francfort"
    XMIL = "XMIL", "Milan"
    XMAD = "XMAD", "Madrid"
    XHEL = "XHEL", "Helsinki"
    XDUB = "XDUB", "Dublin"


class StatutValeur(models.TextChoices):
    PROPOSEE = "proposee", "Proposée"
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class ValeurQuerySet(models.QuerySet):
    def actives(self):
        return self.filter(statut=StatutValeur.ACTIVE)


class Valeur(models.Model):
    """Titre suivi (ticker au format Yahoo, ex. TTE.PA)."""

    ticker = models.CharField(max_length=20, unique=True)
    nom = models.CharField(max_length=200)
    place = models.CharField(max_length=10, choices=Place.choices)
    devise = models.CharField(max_length=3, choices=[("USD", "USD"), ("EUR", "EUR")])
    # Noms séparés par des virgules, pour reconnaître la valeur dans une nouvelle.
    alias = models.TextField(blank=True)
    statut = models.CharField(
        max_length=10, choices=StatutValeur.choices, default=StatutValeur.PROPOSEE
    )
    imposee = models.BooleanField(default=False)

    objects = ValeurQuerySet.as_manager()

    class Meta:
        ordering = ["ticker"]

    def __str__(self):
        return self.ticker


class Bougie(models.Model):
    valeur = models.ForeignKey(Valeur, on_delete=models.CASCADE, related_name="bougies")
    intervalle = models.CharField(max_length=2, choices=[("5m", "5 minutes"), ("1d", "1 jour")])
    debut = models.DateTimeField()  # UTC
    ouverture = models.DecimalField(max_digits=14, decimal_places=4)
    haut = models.DecimalField(max_digits=14, decimal_places=4)
    bas = models.DecimalField(max_digits=14, decimal_places=4)
    cloture = models.DecimalField(max_digits=14, decimal_places=4)
    volume = models.BigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["valeur", "intervalle", "debut"], name="bougie_unique"
            )
        ]

    def __str__(self):
        return f"{self.valeur} {self.intervalle} {self.debut:%Y-%m-%d %H:%M}"


class TauxChange(models.Model):
    devise = models.CharField(max_length=3)
    instant = models.DateTimeField()
    taux = models.DecimalField(max_digits=14, decimal_places=6)  # EUR pour 1 unité de la devise

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["devise", "instant"], name="taux_unique")
        ]

    def __str__(self):
        return f"{self.devise} {self.instant:%Y-%m-%d %H:%M}"

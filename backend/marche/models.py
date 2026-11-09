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


class TypeTitre(models.TextChoices):
    ACTION = "action", "Action"
    ETF = "etf", "ETF"


class ValeurQuerySet(models.QuerySet):
    def actives(self):
        return self.filter(statut=StatutValeur.ACTIVE)

    def detenues(self):
        """Valeurs d'une position ouverte (quel que soit leur statut)."""
        # Modèle lu par la relation inverse : `marche` n'importe pas `portefeuille`.
        position = self.model._meta.get_field("positions").related_model
        return self.filter(
            models.Exists(position.objects.filter(valeur=models.OuterRef("pk"), fermee_le__isnull=True))
        )

    def a_relever(self):
        """Valeurs dont les cours sont relevés : actives, références, et toute valeur encore détenue.

        Une valeur désactivée avec une position ouverte reste relevée : ses stops et ses signaux de
        vente doivent pouvoir s'exécuter jusqu'à la sortie.
        """
        return self.filter(
            models.Q(statut=StatutValeur.ACTIVE) | models.Q(reference=True) | models.Q(pk__in=self.detenues())
        )


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
    # Suivie pour comparaison (ex. IWDA.AS) : jamais tradée, hors de la limite de l'univers.
    reference = models.BooleanField(default=False)
    type_titre = models.CharField(
        max_length=10, choices=TypeTitre.choices, default=TypeTitre.ACTION
    )

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

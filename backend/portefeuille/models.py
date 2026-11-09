from decimal import Decimal

from django.db import models
from django.db.models import Q


class SensOrdre(models.TextChoices):
    ACHAT = "achat", "Achat"
    VENTE = "vente", "Vente"


class ActionDecision(models.TextChoices):
    ACHETER = "acheter", "Acheter"
    VENDRE = "vendre", "Vendre"
    GARDER = "garder", "Garder"
    REFUSER = "refuser", "Refuser"


class Portefeuille(models.Model):
    """Portefeuille simulé et ses règles (montants en EUR)."""

    nom = models.CharField(max_length=50, unique=True)
    broker = models.CharField(max_length=20, default="simule")
    # Barème de frais appliqué (courtage.Bareme.broker).
    bareme_broker = models.CharField(max_length=20, default="ibkr")
    capital_initial = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("10000"))
    liquidites = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("10000"))
    # Part maximale d'une position dans le portefeuille, nombre maximal de positions.
    part_max = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.05"))
    positions_max = models.PositiveIntegerField(default=20)
    # Stop de perte et stop suiveur (seuil d'armement, écart au plus haut), en ratio.
    stop_perte = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.05"))
    seuil_suiveur = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.05"))
    ecart_suiveur = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.05"))
    # Frais maximaux d'un ordre, rapportés à son montant.
    frais_max_relatifs = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.01"))
    score_achat = models.IntegerField(default=2)
    utilise_ia = models.BooleanField(default=False)
    budget_ia_mensuel = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("40"))
    # Indice de comparaison : mêmes versements placés en parts de l'indice.
    indice = models.ForeignKey("marche.Valeur", on_delete=models.PROTECT, related_name="+")
    indice_quantite = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal("0"))
    indice_liquidites = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    demarre = models.DateTimeField(null=True, blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Position(models.Model):
    """Titre détenu (ouverte) ou revendu (fermée). Prix dans la devise de la valeur."""

    portefeuille = models.ForeignKey(Portefeuille, on_delete=models.CASCADE, related_name="positions")
    valeur = models.ForeignKey("marche.Valeur", on_delete=models.PROTECT, related_name="positions")
    quantite = models.PositiveIntegerField()
    prix_entree = models.DecimalField(max_digits=14, decimal_places=4)
    taux_entree = models.DecimalField(max_digits=14, decimal_places=6)
    # Montant payé + frais.
    cout_entree_eur = models.DecimalField(max_digits=14, decimal_places=2)
    plus_haut = models.DecimalField(max_digits=14, decimal_places=4)
    ouverte_le = models.DateTimeField()
    fermee_le = models.DateTimeField(null=True, blank=True)
    prix_sortie = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    # Montant encaissé − frais.
    produit_sortie_eur = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    motif_sortie = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-ouverte_le"]
        constraints = [
            models.UniqueConstraint(
                fields=["portefeuille", "valeur"],
                condition=Q(fermee_le__isnull=True),
                name="une_position_ouverte_par_valeur",
            )
        ]

    def __str__(self):
        return f"{self.portefeuille} {self.valeur.ticker} x{self.quantite}"

    @property
    def resultat_eur(self):
        """Produit de sortie − coût d'entrée ; None tant que la position est ouverte."""
        if self.fermee_le is None or self.produit_sortie_eur is None:
            return None
        return self.produit_sortie_eur - self.cout_entree_eur


class Decision(models.Model):
    """Décision d'un cycle, exécutée à la séance suivante (`pour_le`)."""

    portefeuille = models.ForeignKey(Portefeuille, on_delete=models.CASCADE, related_name="decisions")
    valeur = models.ForeignKey(
        "marche.Valeur", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    instant = models.DateTimeField()
    action = models.CharField(max_length=10, choices=ActionDecision.choices)
    motif = models.TextField()
    signaux = models.JSONField(default=dict, blank=True)
    pour_le = models.DateField(null=True, blank=True)
    executee = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-instant"]

    def __str__(self):
        return f"{self.portefeuille} {self.action} {self.valeur_id or ''}"


class Ordre(models.Model):
    """Ordre simulé exécuté, avec le détail des frais (EUR)."""

    portefeuille = models.ForeignKey(Portefeuille, on_delete=models.CASCADE, related_name="ordres")
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="ordres")
    sens = models.CharField(max_length=10, choices=SensOrdre.choices)
    quantite = models.PositiveIntegerField()
    prix = models.DecimalField(max_digits=14, decimal_places=4)
    taux_eur = models.DecimalField(max_digits=14, decimal_places=6)
    montant_eur = models.DecimalField(max_digits=14, decimal_places=2)
    courtage = models.DecimalField(max_digits=14, decimal_places=2)
    change = models.DecimalField(max_digits=14, decimal_places=2)
    tob = models.DecimalField(max_digits=14, decimal_places=2)
    frais_total = models.DecimalField(max_digits=14, decimal_places=2)
    instant = models.DateTimeField()
    decision = models.ForeignKey(
        Decision, null=True, blank=True, on_delete=models.SET_NULL, related_name="ordres"
    )

    class Meta:
        ordering = ["-instant"]

    def __str__(self):
        return f"{self.sens} {self.quantite} {self.position.valeur.ticker}"


class Valorisation(models.Model):
    """Photo périodique de la valeur du portefeuille et de son indice de comparaison."""

    portefeuille = models.ForeignKey(Portefeuille, on_delete=models.CASCADE, related_name="valorisations")
    instant = models.DateTimeField()
    liquidites = models.DecimalField(max_digits=14, decimal_places=2)
    titres = models.DecimalField(max_digits=14, decimal_places=2)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    indice_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["instant"]
        constraints = [
            models.UniqueConstraint(
                fields=["portefeuille", "instant"], name="une_valorisation_par_instant"
            )
        ]

    def __str__(self):
        return f"{self.portefeuille} {self.instant:%Y-%m-%d %H:%M}"

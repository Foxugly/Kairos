from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import models

from marche.models import TypeTitre


@dataclass(frozen=True)
class RegleDonnees:
    places: tuple[str, ...]
    devise: str
    par_action: Decimal
    pourcentage: Decimal
    minimum: Decimal
    maximum_pourcentage: Decimal | None
    maximum: Decimal | None


@dataclass(frozen=True)
class TobDonnees:
    type_titre: str
    taux: Decimal
    plafond: Decimal


@dataclass(frozen=True)
class BaremeDonnees:
    """Copie immuable d'un barème, sans base de données : partagée par le backtest et le cycle."""

    broker: str
    nom: str
    change_pourcentage: Decimal
    change_minimum: Decimal
    glissement: Decimal
    regles: tuple[RegleDonnees, ...]
    tob: tuple[TobDonnees, ...]


class Bareme(models.Model):
    """Barème de frais d'un courtier, valable à partir d'une date.

    Les taux sont des fractions : 0,0005 = 0,05 %.
    """

    broker = models.CharField(max_length=20)
    nom = models.CharField(max_length=100)
    valide_depuis = models.DateField()
    # Frais de change : fraction du montant, avec un minimum en EUR.
    change_pourcentage = models.DecimalField(max_digits=8, decimal_places=6, default=0)
    change_minimum = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    # Écart de prix appliqué aux ordres simulés (fraction du cours).
    glissement = models.DecimalField(max_digits=8, decimal_places=6, default=Decimal("0.001"))
    # Sources (URL, date du relevé) et réserves.
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["broker", "-valide_depuis"]

    def __str__(self):
        return f"{self.nom} ({self.valide_depuis})"

    @classmethod
    def en_vigueur(cls, broker: str, jour: date) -> "Bareme":
        """Barème le plus récent dont `valide_depuis` ne dépasse pas `jour` (IndexError si aucun)."""
        return cls.objects.filter(broker=broker, valide_depuis__lte=jour).order_by(
            "-valide_depuis"
        )[0]

    def donnees(self) -> BaremeDonnees:
        return BaremeDonnees(
            broker=self.broker,
            nom=self.nom,
            change_pourcentage=self.change_pourcentage,
            change_minimum=self.change_minimum,
            glissement=self.glissement,
            regles=tuple(
                RegleDonnees(
                    places=tuple(p.strip() for p in r.places.split(",") if p.strip()),
                    devise=r.devise,
                    par_action=r.par_action,
                    pourcentage=r.pourcentage,
                    minimum=r.minimum,
                    maximum_pourcentage=r.maximum_pourcentage,
                    maximum=r.maximum,
                )
                for r in self.regles.order_by("id")
            ),
            tob=tuple(
                TobDonnees(type_titre=t.type_titre, taux=t.taux, plafond=t.plafond)
                for t in self.tob.order_by("id")
            ),
        )


class RegleCourtage(models.Model):
    bareme = models.ForeignKey(Bareme, on_delete=models.CASCADE, related_name="regles")
    # Codes `Place` séparés par des virgules.
    places = models.CharField(max_length=100)
    devise = models.CharField(max_length=3)
    par_action = models.DecimalField(max_digits=8, decimal_places=5, default=0)
    pourcentage = models.DecimalField(max_digits=8, decimal_places=6, default=0)
    minimum = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    # Plafonds : fraction du montant de l'ordre, et/ou montant absolu (devise de la règle).
    maximum_pourcentage = models.DecimalField(
        max_digits=8, decimal_places=6, null=True, blank=True
    )
    maximum = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.places} ({self.devise})"


class TauxTob(models.Model):
    """Taxe belge sur les opérations de bourse : taux (fraction) et plafond par ordre en EUR."""

    bareme = models.ForeignKey(Bareme, on_delete=models.CASCADE, related_name="tob")
    type_titre = models.CharField(max_length=10, choices=TypeTitre.choices)
    taux = models.DecimalField(max_digits=8, decimal_places=6)
    plafond = models.DecimalField(max_digits=8, decimal_places=2)

    def __str__(self):
        return f"{self.type_titre} {self.taux}"

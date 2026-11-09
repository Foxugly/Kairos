import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from marche.models import Place, StatutValeur, Valeur

FICHIER_PAR_DEFAUT = Path(__file__).resolve().parents[2] / "donnees" / "univers.csv"


class Command(BaseCommand):
    help = "Propose l'univers de titres (valeurs imposées, S&P 100, Euro Stoxx 50) depuis un CSV."

    def add_arguments(self, parser):
        parser.add_argument("--fichier", default=str(FICHIER_PAR_DEFAUT))

    def handle(self, *args, **options):
        places = set(Place.values)
        crees = maj = 0
        # Tout ou rien : une ligne invalide n'écrit rien.
        with transaction.atomic():
            with open(options["fichier"], encoding="utf-8", newline="") as f:
                # L'en-tête est la ligne 1 : les données commencent à la ligne 2.
                for numero, ligne in enumerate(csv.DictReader(f), start=2):
                    if ligne["place"] not in places:
                        raise CommandError(
                            f"ligne {numero} : place inconnue « {ligne['place']} »"
                        )
                    imposee = ligne["imposee"] == "1"
                    _, cree = Valeur.objects.update_or_create(
                        ticker=ligne["ticker"],
                        defaults={
                            "nom": ligne["nom"],
                            "alias": ligne["alias"],
                            "place": ligne["place"],
                            "devise": ligne["devise"],
                            "imposee": imposee,
                        },
                        # Le statut n'est fixé qu'à la création : on ne réactive
                        # jamais une valeur que l'administrateur a désactivée.
                        create_defaults={
                            "nom": ligne["nom"],
                            "alias": ligne["alias"],
                            "place": ligne["place"],
                            "devise": ligne["devise"],
                            "imposee": imposee,
                            "statut": (
                                StatutValeur.ACTIVE if imposee else StatutValeur.PROPOSEE
                            ),
                        },
                    )
                    if cree:
                        crees += 1
                    else:
                        maj += 1
        self.stdout.write(f"{crees} valeurs créées, {maj} mises à jour")

from decimal import Decimal

from django.db import migrations


def creer_portefeuilles(apps, schema_editor):
    Valeur = apps.get_model("marche", "Valeur")
    Portefeuille = apps.get_model("portefeuille", "Portefeuille")
    # Mêmes champs que la ligne du CSV d'univers : `proposer_univers` reste cohérente.
    indice, _ = Valeur.objects.get_or_create(
        ticker="IWDA.AS",
        defaults={
            "nom": "iShares Core MSCI World",
            "place": "XAMS",
            "devise": "EUR",
            "alias": "",
            "imposee": False,
            "reference": True,
            "type_titre": "etf",
        },
    )
    for nom, utilise_ia in (("IA", True), ("Technique", False)):
        Portefeuille.objects.get_or_create(
            nom=nom,
            defaults={
                "utilise_ia": utilise_ia,
                "capital_initial": Decimal("10000"),
                "liquidites": Decimal("10000"),
                "indice": indice,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("portefeuille", "0001_initial"),
        ("marche", "0002_reference_type_titre"),
    ]

    operations = [migrations.RunPython(creer_portefeuilles, migrations.RunPython.noop)]

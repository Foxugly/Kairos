from marche.models import Valeur
from portefeuille.models import Portefeuille


def repartir_de_zero():
    """Retire les données de départ des migrations (portefeuilles, IWDA.AS) pour les tests qui comptent les valeurs."""
    Portefeuille.objects.all().delete()
    Valeur.objects.all().delete()

from datetime import date
from decimal import Decimal

from django.db import migrations

NOTES = """IBKR Pro, tarification fixe (« IBKR Pro – fixe »). Relevé du 2026-11-09.
Sources visées : https://www.interactivebrokers.ie/en/pricing/commissions-stocks.php et
https://www.interactivebrokers.ie/en/pricing/commissions-stocks-europe.php. Ces pages ont répondu
HTTP 403 au relevé automatique : les valeurs viennent de recoupements secondaires (page IBKR des
commissions https://www.interactivebrokers.com/en/pricing/commissions-home.php, brokerchooser.com,
eupersonalfinance.eu) et sont à revérifier à la main.
- Actions US : 0,005 USD par action, minimum 1 USD, maximum 1 % du montant (confirmé par recoupement).
- Europe : 0,05 % du montant, minimum 3 EUR, sans maximum, pour Euronext (Paris, Amsterdam, Bruxelles),
  Xetra, Borsa Italiana, BME Madrid, Nasdaq Helsinki et Euronext Dublin. NON CONFIRMÉ place par place
  (Euronext vu dans deux sources secondaires ; les autres places sont alignées par défaut ; le
  plafond de 29 EUR relevé ici et là concerne la tarification dégressive, pas la fixe).
- Change : commission de 0,20 point de base (0,002 %), minimum 2 USD, ici arrondi à 2 EUR
  (https://www.interactivebrokers.ca/en/trading/products-stocks.php). NON CONFIRMÉ pour le
  site UE ; la conversion automatique est parfois décrite avec 0,03 % en plus (non retenu).
- Frais de bourse et de régulation au-delà de la commission : ignorés (la tarification fixe les inclut).
- TOB belge : actions 0,35 % plafonnée à 1 600 EUR ; ETF capitalisant non enregistré en Belgique
  (IWDA) 0,12 % plafonnée à 1 300 EUR (https://curvo.eu/fr/article/taxe-boursiere-tob,
  https://fin.belgium.be/fr/particuliers/international/revenus-comptes-etrangers/taxe-operations-bourse).
  Un ETF capitalisant enregistré en Belgique serait à 1,32 % plafonnée à 4 000 EUR : non géré.
- IBKR ne prélève pas la TOB (courtier étranger, curvo.eu) : le résident belge la déclare et la paie
  lui-même sur MyMinfin. Elle est tout de même comptée dans les frais simulés. Source secondaire."""

EUROPE = "XPAR,XAMS,XBRU,XETR,XMIL,XMAD,XHEL,XDUB"


def creer(apps, schema_editor):
    Bareme = apps.get_model("courtage", "Bareme")
    b = Bareme.objects.create(
        broker="ibkr",
        nom="IBKR Pro – fixe",
        valide_depuis=date(2026, 11, 9),
        change_pourcentage=Decimal("0.000020"),
        change_minimum=Decimal("2.00"),
        glissement=Decimal("0.001"),
        notes=NOTES,
    )
    b.regles.create(
        places="NASDAQ,NYSE", devise="USD", par_action=Decimal("0.005"),
        minimum=Decimal("1.00"), maximum_pourcentage=Decimal("0.01"),
    )
    b.regles.create(
        places=EUROPE, devise="EUR", pourcentage=Decimal("0.0005"), minimum=Decimal("3.00"),
    )
    b.tob.create(type_titre="action", taux=Decimal("0.0035"), plafond=Decimal("1600.00"))
    b.tob.create(type_titre="etf", taux=Decimal("0.0012"), plafond=Decimal("1300.00"))


def supprimer(apps, schema_editor):
    apps.get_model("courtage", "Bareme").objects.filter(broker="ibkr").delete()


class Migration(migrations.Migration):
    dependencies = [("courtage", "0001_initial")]
    operations = [migrations.RunPython(creer, supprimer)]

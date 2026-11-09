from django.core.management.base import BaseCommand

from cycle.deroulement import lancer


class Command(BaseCommand):
    help = "Lance un cycle de collecte (nouvelles, cours…). Code de sortie 0 même si une étape échoue."

    def handle(self, *args, **options):
        cycle = lancer()
        if cycle is None:
            self.stdout.write("Cycle ignoré : un cycle est déjà en cours.")
            return
        duree = (cycle.fin - cycle.debut).total_seconds()
        etapes = ", ".join(
            f"{nom}={'ERREUR' if 'erreur' in res else 'ok'}" for nom, res in cycle.journal.items()
        )
        self.stdout.write(f"Cycle {cycle.pk} {cycle.statut} en {duree:.1f}s ({etapes})")

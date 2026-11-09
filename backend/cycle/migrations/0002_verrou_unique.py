from django.db import migrations


def creer_verrou(apps, schema_editor):
    # Ligne unique sur laquelle `lancer` prend son verrou (voir cycle.models.Verrou).
    apps.get_model("cycle", "Verrou").objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("cycle", "0001_initial")]

    operations = [migrations.RunPython(creer_verrou, migrations.RunPython.noop)]

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("influencers", "0019_outreachtask_owners")]

    # V2.44.102 replaces the list hot paths with count-free pagination and
    # lightweight serializers. Keep the migration number for graph stability,
    # but avoid blocking production tables with optional index DDL.
    operations = []

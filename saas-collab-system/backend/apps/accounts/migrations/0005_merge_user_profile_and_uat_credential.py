from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_user_full_name_and_profile_departments"),
        ("accounts", "0004_customuser_uat_credential_lease"),
    ]

    operations = []

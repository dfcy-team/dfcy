import json
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from apps.integrations.lazada_archive_import import import_archive


class Command(BaseCommand):
    help = "导入现有Lazada授权，不刷新；默认只预览。不会输出任何密钥。"

    def add_arguments(self, parser):
        parser.add_argument("--archive", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"], is_active=True)
            result = import_archive(options["archive"], actor=actor, commit=options["commit"])
        except Exception:
            raise CommandError("Lazada授权导入未完成，请检查店铺身份、应用、权限及托管服务；未尝试刷新，未输出凭据。") from None
        self.stdout.write(json.dumps(result, ensure_ascii=False))

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.releases.models import ReleaseContract, ReleaseGateResult
from apps.releases.services import (
    create_release_contract,
    record_gate_result,
    required_gate_codes,
    submit_release_contract,
)
from apps.tenants.models import Tenant


GATE_CATEGORIES = {
    "engineering-quality": "engineering",
    "miniapp-special": "miniapp",
    "backend-compatibility": "backend",
    "end-to-end": "testing",
    "release-readiness": "release",
    "evidence-integrity": "governance",
    "miniapp-filing-approved": "compliance",
}


class Command(BaseCommand):
    help = "Seed one idempotent local-only release contract for Mini Program acceptance."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-code", required=True)
        parser.add_argument("--viewer-username", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Local release acceptance data requires DEBUG=True.")

        try:
            tenant = Tenant.objects.get(code=options["tenant_code"])
            viewer = CustomUser.objects.get(
                username=options["viewer_username"],
                tenant=tenant,
                is_active=True,
            )
        except (Tenant.DoesNotExist, CustomUser.DoesNotExist) as exc:
            raise CommandError("The target local tenant or viewer does not exist.") from exc
        if viewer.user_type != CustomUser.UserType.INTERNAL:
            raise CommandError("The target viewer must be an internal user.")

        fixture_username = f"{viewer.username}_release_fixture_operator"
        operator, _ = CustomUser.objects.get_or_create(
            username=fixture_username,
            defaults={
                "tenant": tenant,
                "user_type": CustomUser.UserType.INTERNAL,
                "is_active": True,
            },
        )
        if operator.tenant_id != tenant.id or operator.user_type != CustomUser.UserType.INTERNAL:
            raise CommandError("The fixture operator conflicts with another account.")
        operator.set_unusable_password()
        operator.save(update_fields=["password"])

        manage_permission = Permission.objects.get(code="release.contract.manage")
        role, _ = Role.objects.update_or_create(
            tenant=tenant,
            code="local-release-fixture-manager",
            defaults={
                "name": "Local Release Fixture Manager",
                "status": Role.Status.ACTIVE,
            },
        )
        role.permissions.set([manage_permission])
        UserRole.objects.get_or_create(tenant=tenant, user=operator, role=role)
        DataScope.objects.update_or_create(
            tenant=tenant,
            role=role,
            scope_type=DataScope.ScopeType.ALL,
            defaults={"config": {"all": True}},
        )

        payload = {
            "application_code": "saas-collab-miniapp",
            "environment": ReleaseContract.Environment.TEST,
            "commit_sha": "7f3c9e1a4b6d8f20517394ace0bd621ea83f90c2",
            "api_contract_version": "miniapp-auth-release-v1",
            "scope": [
                "真实微信登录",
                "发布合同只读工作台",
                "合同详情与门禁证据",
            ],
            "risk_level": ReleaseContract.RiskLevel.LOW,
            "rollback_version": "local-acceptance-previous",
            "rollback_point": "恢复本地 Mock 登录和只读合同基线",
            "stop_conditions": [
                "登录接口非预期 5xx",
                "租户隔离或只读权限失效",
                "敏感字段进入响应或日志",
            ],
            "observation_minutes": 30,
        }
        key_prefix = f"local-release-acceptance:{tenant.code}:v1"
        contract, _ = create_release_contract(
            actor=operator,
            payload=payload,
            idempotency_key=f"{key_prefix}:create",
        )

        evaluated_at = timezone.now()
        expires_at = evaluated_at + timedelta(days=7)
        required_codes = required_gate_codes(contract)
        for gate_code in required_codes:
            contract.refresh_from_db()
            record_gate_result(
                contract=contract,
                actor=operator,
                payload={
                    "code": gate_code,
                    "category": GATE_CATEGORIES[gate_code],
                    "status": ReleaseGateResult.Status.PASSED,
                    "evidence_ref": f"local://acceptance/{gate_code}",
                    "evaluated_at": evaluated_at,
                    "expires_at": expires_at,
                    "version": contract.version,
                },
                idempotency_key=f"{key_prefix}:gate:{gate_code}",
            )

        contract.refresh_from_db()
        if contract.status == ReleaseContract.Status.DRAFT:
            contract, _ = submit_release_contract(
                contract=contract,
                actor=operator,
                version=contract.version,
                reason="Local Mini Program read-only acceptance review.",
                idempotency_key=f"{key_prefix}:submit",
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Local release acceptance contract ready: id={contract.id}, "
                f"contract_no={contract.contract_no}, status={contract.status}, "
                f"gates={contract.gate_results.count()}/{len(required_codes)}"
            )
        )

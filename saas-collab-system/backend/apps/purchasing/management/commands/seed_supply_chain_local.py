from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.masterdata.models import SupplierMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.purchasing.models import SupplyPurchaseOrder, SupplyPurchaseOrderLine
from apps.tenants.models import Tenant


PERMISSION_CODES = (
    "supply.purchase_order.view",
    "supply.purchase_order.create",
    "supply.purchase_order.accept",
    "supply.purchase_order.assign_shipping_route",
    "supply.production.start",
    "supply.production.update",
    "supply.production.complete",
)


class Command(BaseCommand):
    help = "Create idempotent, credential-free SC-F1 sample data in an explicitly local database."

    def handle(self, *args, **options):
        database_name = str(connection.settings_dict.get("NAME") or "").lower()
        if not settings.DEBUG or not any(marker in database_name for marker in ("local", "dev", "test")):
            raise CommandError("This command is restricted to an explicitly local development/test database.")

        with transaction.atomic():
            tenant, _ = Tenant.objects.get_or_create(
                code="scm-f1-local",
                defaults={"name": "SC-F1 Local Development"},
            )
            internal, _ = CustomUser.objects.get_or_create(
                username="scm-f1-local-internal",
                defaults={
                    "tenant": tenant,
                    "user_type": CustomUser.UserType.INTERNAL,
                    "email": "",
                },
            )
            if internal.tenant_id != tenant.id or internal.user_type != CustomUser.UserType.INTERNAL:
                raise CommandError("The reserved local internal username is already used by another identity.")
            internal.set_unusable_password()
            internal.save(update_fields=["password"])

            role, _ = Role.objects.get_or_create(
                tenant=tenant,
                code="scm-f1-local-manager",
                defaults={"name": "SC-F1 Local Manager"},
            )
            permissions = list(Permission.objects.filter(code__in=PERMISSION_CODES))
            if len(permissions) != len(PERMISSION_CODES):
                raise CommandError("SC-F1 permission migration has not been applied.")
            role.permissions.add(*permissions)
            UserRole.objects.get_or_create(tenant=tenant, user=internal, role=role)
            DataScope.objects.get_or_create(
                tenant=tenant,
                role=role,
                scope_type=DataScope.ScopeType.ALL,
                defaults={"config": {}},
            )

            supplier, _ = SupplierMaster.objects.get_or_create(
                tenant=tenant,
                code="scm-f1-demo-supplier",
                defaults={
                    "name": "SC-F1 本地演示供应商",
                    "contact_alias": "Local only",
                },
            )
            supplier_user, _ = CustomUser.objects.get_or_create(
                username="scm-f1-local-supplier",
                defaults={
                    "tenant": tenant,
                    "user_type": CustomUser.UserType.EXTERNAL,
                    "email": "",
                },
            )
            if supplier_user.tenant_id != tenant.id or supplier_user.user_type != CustomUser.UserType.EXTERNAL:
                raise CommandError("The reserved local supplier username is already used by another identity.")
            supplier_user.set_unusable_password()
            supplier_user.save(update_fields=["password"])
            ExternalUserProfile.objects.update_or_create(
                user=supplier_user,
                defaults={
                    "tenant": tenant,
                    "supplier_id": supplier.id,
                    "company_name": supplier.name,
                    "contact_name": "Local only",
                },
            )

            spu, _ = ProductSPU.objects.get_or_create(
                tenant=tenant,
                spu_code="SC-F1-DEMO-SPU",
                defaults={"product_name": "SC-F1 本地演示商品"},
            )
            sku, _ = ProductSKU.objects.get_or_create(
                tenant=tenant,
                sku_code="SC-F1-DEMO-SKU",
                defaults={"spu": spu},
            )
            if sku.spu_id != spu.id:
                raise CommandError("The reserved local SKU is already bound to a different SPU.")

            order, created = SupplyPurchaseOrder.objects.get_or_create(
                tenant=tenant,
                order_no="SC-F1-LOCAL-001",
                defaults={
                    "supplier": supplier,
                    "order_date": date.today(),
                    "expected_delivery_date": date.today() + timedelta(days=30),
                    "currency": "CNY",
                    "notes": "Credential-free local development sample; never production data.",
                    "created_by": internal,
                    "creation_idempotency_key": "seed-scm-f1-local-order",
                    "creation_request_hash": "0" * 64,
                },
            )
            if order.supplier_id != supplier.id:
                raise CommandError("The reserved local order number is already bound to a different supplier.")
            if not order.creation_idempotency_key:
                order.creation_idempotency_key = "seed-scm-f1-local-order"
                order.creation_request_hash = "0" * 64
                order.save(update_fields=["creation_idempotency_key", "creation_request_hash", "updated_at"])
            SupplyPurchaseOrderLine.objects.get_or_create(
                order=order,
                line_no=1,
                defaults={
                    "tenant": tenant,
                    "sku": sku,
                    "sku_code_snapshot": sku.sku_code,
                    "product_name_snapshot": spu.product_name,
                    "quantity": 100,
                    "unit_price": "12.5000",
                    "expected_delivery_date": order.expected_delivery_date,
                },
            )

        verb = "created" if created else "reused"
        self.stdout.write(
            self.style.SUCCESS(
                f"SC-F1 local sample {verb}: tenant_id={tenant.id}, "
                f"supplier_id={supplier.id}, sku_id={sku.id}, order_id={order.id}. "
                "Both sample users have unusable passwords."
            )
        )

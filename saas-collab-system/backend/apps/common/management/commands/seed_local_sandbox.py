import os
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from apps.accounts.models import CustomUser, ExternalUserProfile, InternalUserProfile
from apps.finance.models import ReconciliationMatch
from apps.finance.services import (
    import_demo_bank_receipt,
    import_demo_statement,
    import_demo_withdrawal,
    run_mock_reconciliation,
)
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU, ProductStatus, ProductStatusSnapshot
from apps.purchasing.models import PurchaseOrder
from apps.suppliers.models import SupplierPerformanceSnapshot, SupplierShipment, SupplierTask
from apps.tenants.models import Tenant


MODULES = (
    "core",
    "sales-inventory-finance-reconciliation",
    "creator-management",
    "procurement",
    "integration",
)


class Command(BaseCommand):
    help = "Create deterministic synthetic data for an explicitly confirmed local Sandbox database."

    def add_arguments(self, parser):
        parser.add_argument("--module", choices=MODULES, default="core")
        parser.add_argument(
            "--confirm-local",
            action="store_true",
            help="Required acknowledgement that the target is a disposable local Sandbox.",
        )

    def handle(self, *args, **options):
        self._validate_environment(options)
        password = os.getenv("LOCAL_SANDBOX_DEMO_PASSWORD", "")
        if len(password) < 16:
            raise CommandError("LOCAL_SANDBOX_DEMO_PASSWORD must contain at least 16 characters.")

        with transaction.atomic():
            call_command("sync_permissions", verbosity=0)
            context = self._seed_core(password)
            module = options["module"]
            if module in {"sales-inventory-finance-reconciliation", "integration"}:
                self._seed_sales_inventory_finance(context)
            if module in {"creator-management", "integration"}:
                self._seed_creator_management(context)
            if module in {"procurement", "integration"}:
                self._seed_procurement(context)

        self.stdout.write(
            self.style.SUCCESS(
                f"LOCAL_SANDBOX_SEED=PASS module={module} tenants=2 "
                f"users={CustomUser.objects.filter(username__startswith='local_').count()}"
            )
        )

    def _validate_environment(self, options):
        if not options["confirm_local"]:
            raise CommandError("Refusing to seed without --confirm-local.")
        if os.getenv("LOCAL_SANDBOX_ENVIRONMENT") != "local-sandbox":
            raise CommandError("LOCAL_SANDBOX_ENVIRONMENT must be local-sandbox.")
        if not settings.DEBUG:
            raise CommandError("Local Sandbox seeding requires DEBUG=true.")
        if os.getenv("SANDBOX_ALLOW_REAL_PLATFORM", "false").lower() != "false":
            raise CommandError("Real platform access must remain disabled.")
        if os.getenv("SANDBOX_ALLOW_HIGH_RISK_AUTOMATION", "false").lower() != "false":
            raise CommandError("High-risk automation must remain disabled.")

        database_name = str(connection.settings_dict.get("NAME") or "")
        database_host = str(connection.settings_dict.get("HOST") or "")
        if not database_name.startswith("saas_collab_local_"):
            raise CommandError("Database name must start with saas_collab_local_.")
        if database_host not in {"mysql", "localhost", "127.0.0.1"}:
            raise CommandError("Database host is not approved for Local Sandbox seeding.")

    def _seed_core(self, password):
        tenant_a, _ = Tenant.objects.update_or_create(
            code="local-sandbox-a",
            defaults={"name": "Local Sandbox Tenant A", "status": Tenant.Status.ACTIVE},
        )
        tenant_b, _ = Tenant.objects.update_or_create(
            code="local-sandbox-b",
            defaults={"name": "Local Sandbox Tenant B", "status": Tenant.Status.ACTIVE},
        )

        users = {
            "operator": self._user(tenant_a, "local_internal_operator", CustomUser.UserType.INTERNAL, password),
            "finance": self._user(tenant_a, "local_finance_reviewer", CustomUser.UserType.INTERNAL, password),
            "creator": self._user(tenant_a, "local_creator_operator", CustomUser.UserType.INTERNAL, password),
            "supplier": self._user(tenant_a, "local_supplier_a", CustomUser.UserType.EXTERNAL, password),
            "rpa": self._user(tenant_a, "local_rpa_agent", CustomUser.UserType.RPA, password),
            "other_tenant": self._user(
                tenant_b, "local_other_tenant_viewer", CustomUser.UserType.INTERNAL, password
            ),
        }

        InternalUserProfile.objects.get_or_create(user=users["operator"], defaults={"tenant": tenant_a})
        InternalUserProfile.objects.get_or_create(user=users["finance"], defaults={"tenant": tenant_a})
        InternalUserProfile.objects.get_or_create(user=users["creator"], defaults={"tenant": tenant_a})
        InternalUserProfile.objects.get_or_create(user=users["other_tenant"], defaults={"tenant": tenant_b})
        ExternalUserProfile.objects.update_or_create(
            user=users["supplier"],
            defaults={
                "tenant": tenant_a,
                "supplier_id": 1001,
                "company_name": "Synthetic Supplier A",
                "contact_name": "Demo Contact",
            },
        )

        sales_role = self._role(
            tenant_a,
            "sales_inventory_viewer",
            (
                "analytics.view",
                "products.master.view",
                "products.status.view",
                "replenishment.view",
                "alerts.view",
            ),
        )
        finance_role = self._role(
            tenant_a,
            "finance_reconciler",
            ("finance.view", "finance.reconcile", "finance.exception.handle"),
        )
        procurement_role = self._role(
            tenant_a,
            "procurement_operator",
            (
                "purchasing.orders.view",
                "purchasing.orders.manage",
                "suppliers.performance.view",
                "suppliers.performance.calculate",
            ),
        )
        creator_role = self._role(tenant_a, "creator_mock_viewer", ())
        other_role = self._role(tenant_b, "other_tenant_viewer", ("analytics.view",))

        self._assign(users["operator"], sales_role)
        self._assign(users["operator"], procurement_role)
        self._assign(users["finance"], finance_role)
        self._assign(users["creator"], creator_role)
        self._assign(users["other_tenant"], other_role)

        return {"tenant_a": tenant_a, "tenant_b": tenant_b, **users}

    def _user(self, tenant, username, user_type, password):
        user, created = CustomUser.objects.get_or_create(
            username=username,
            defaults={
                "tenant": tenant,
                "user_type": user_type,
                "email": f"{username}@example.com",
                "is_active": True,
            },
        )
        if not created and (user.tenant_id != tenant.id or user.user_type != user_type):
            raise CommandError(f"Existing local user has an unexpected identity boundary: {username}")
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        user.set_password(password)
        user.save(update_fields=["password", "is_active", "is_staff", "is_superuser"])
        return user

    def _role(self, tenant, code, permission_codes):
        role, _ = Role.objects.update_or_create(
            tenant=tenant,
            code=code,
            defaults={"name": code.replace("_", " ").title(), "status": Role.Status.ACTIVE},
        )
        permissions = list(Permission.objects.filter(code__in=permission_codes))
        if len(permissions) != len(permission_codes):
            found = {permission.code for permission in permissions}
            raise CommandError(f"Permission catalog is missing: {sorted(set(permission_codes) - found)}")
        role.permissions.set(permissions)
        DataScope.objects.update_or_create(
            tenant=tenant,
            role=role,
            scope_type=DataScope.ScopeType.ALL,
            defaults={"config": {"all": True}},
        )
        return role

    def _assign(self, user, role):
        UserRole.objects.get_or_create(tenant=user.tenant, user=user, role=role)

    def _seed_sales_inventory_finance(self, context):
        for suffix, tenant in (("A", context["tenant_a"]), ("B", context["tenant_b"])):
            stock_cases = (
                ("NORMAL", 120, 8, ProductStatus.ACTIVE),
                ("STOCKOUT", 0, 6, ProductStatus.SLOW_MOVING),
                ("OVERSTOCK", 500, 1, ProductStatus.ACTIVE),
            )
            for case, available_stock, average_daily_sales, product_status in stock_cases:
                spu, _ = ProductSPU.objects.update_or_create(
                    tenant=tenant,
                    spu_code=f"LOCAL-SPU-{suffix}-{case}",
                    defaults={
                        "product_name": f"Synthetic Product {suffix} {case.title()}",
                        "category": "local-demo",
                        "lifecycle_status": ProductSPU.LifecycleStatus.ACTIVE,
                        "sales_status": ProductSPU.SalesStatus.ON_SALE,
                    },
                )
                sku, _ = ProductSKU.objects.update_or_create(
                    tenant=tenant,
                    sku_code=f"LOCAL-SKU-{suffix}-{case}",
                    defaults={
                        "spu": spu,
                        "size": "demo-size",
                        "material": "synthetic-material",
                        "selling_points": ["synthetic", "local-only"],
                        "package_weight": Decimal("1.250"),
                    },
                )
                ProductStatusSnapshot.objects.update_or_create(
                    tenant=tenant,
                    sku=sku,
                    source_reference=f"local-sandbox-{suffix.lower()}-{case.lower()}",
                    defaults={
                        "spu": spu,
                        "source": ProductStatusSnapshot.Source.MANUAL,
                        "metrics_payload": {
                            "available_stock": available_stock,
                            "average_daily_sales": average_daily_sales,
                            "inventory_case": case.lower(),
                            "source": "synthetic",
                        },
                        "calculated_status": product_status,
                    },
                )

            finance_cases = (
                (f"demo-platform-{suffix.lower()}-usd", "USD", Decimal("975.00")),
                (f"demo-platform-{suffix.lower()}-eur", "EUR", Decimal("965.00")),
            )
            for platform, currency, receipt_amount in finance_cases:
                import_demo_statement(tenant, platform=platform, currency=currency)
                import_demo_withdrawal(tenant, platform=platform, currency=currency)
                import_demo_bank_receipt(
                    tenant,
                    amount=receipt_amount,
                    account_hint=f"local-demo-{suffix.lower()}-1234",
                    platform=platform,
                    currency=currency,
                )
                run_mock_reconciliation(tenant, platform=platform, currency=currency)

    def _seed_creator_management(self, context):
        role = Role.objects.get(tenant=context["tenant_a"], code="creator_mock_viewer")
        role.name = "Creator Management Mock Viewer"
        role.save(update_fields=["name"])

    def _seed_procurement(self, context):
        today = timezone.now().date()
        for suffix, tenant, supplier_id, actor in (
            ("A", context["tenant_a"], 1001, context["operator"]),
            ("B", context["tenant_b"], 2001, context["other_tenant"]),
        ):
            PurchaseOrder.objects.update_or_create(
                tenant=tenant,
                po_no=f"LOCAL-PO-{suffix}",
                defaults={
                    "sku_code": f"LOCAL-SKU-{suffix}",
                    "supplier_id": supplier_id,
                    "quantity": 100,
                    "unit_price": Decimal("12.50"),
                    "delivery_date": today + timedelta(days=14),
                    "payment_terms": "synthetic-net-30",
                    "status": PurchaseOrder.Status.DRAFT,
                    "approval_status": PurchaseOrder.ApprovalStatus.DRAFT,
                    "created_by": actor,
                },
            )
            SupplierTask.objects.update_or_create(
                tenant=tenant,
                task_no=f"LOCAL-TASK-{suffix}",
                defaults={
                    "supplier_id": supplier_id,
                    "sku_code": f"LOCAL-SKU-{suffix}",
                    "production_quantity": 100,
                    "completed_quantity": 60,
                    "expected_ship_date": today + timedelta(days=10),
                    "status": SupplierTask.Status.IN_PROGRESS,
                    "feedback_note": "synthetic progress only",
                },
            )
            SupplierShipment.objects.update_or_create(
                tenant=tenant,
                shipment_no=f"LOCAL-SHIP-{suffix}",
                defaults={
                    "supplier_id": supplier_id,
                    "sku_code": f"LOCAL-SKU-{suffix}",
                    "ship_quantity": 60,
                    "carton_count": 6,
                    "weight": Decimal("75.000"),
                    "volume": Decimal("1.200"),
                    "shipping_mark": "LOCAL-DEMO",
                    "tracking_no": f"PLACEHOLDER-{suffix}",
                    "attachment_placeholder": "example/shipment-placeholder",
                    "status": SupplierShipment.Status.SUBMITTED,
                },
            )
            SupplierPerformanceSnapshot.objects.update_or_create(
                tenant=tenant,
                supplier_id=supplier_id,
                period_start=today - timedelta(days=30),
                period_end=today,
                defaults={
                    "total_tasks": 10,
                    "on_time_tasks": 8,
                    "overdue_tasks": 1,
                    "exception_tasks": 1,
                    "total_shipments": 8,
                    "accurate_shipments": 7,
                    "feedback_on_time_count": 9,
                    "on_time_rate": Decimal("80.00"),
                    "overdue_rate": Decimal("10.00"),
                    "exception_rate": Decimal("10.00"),
                    "shipment_accuracy_rate": Decimal("87.50"),
                    "feedback_timeliness_rate": Decimal("90.00"),
                    "total_score": Decimal("85.50"),
                },
            )

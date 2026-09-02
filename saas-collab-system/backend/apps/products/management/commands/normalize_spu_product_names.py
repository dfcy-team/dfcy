"""Audit and (optionally) repair SPU names derived from legacy item names."""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.products.models import ProductColor, ProductLegacyItem, ProductSPU
from apps.products.name_normalization import consensus_spu_product_name


class Command(BaseCommand):
    help = (
        "Audit SPU閸熷棗鎼ч崥宥囆?derived from old 閸熷棗鎼ч崥宥囆?values. "
        "The default is a dry-run; pass --apply to update only ProductSPU.product_name."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist safe changes. Without this flag the command only reports planned changes.",
        )
        parser.add_argument(
            "--tenant-id",
            type=int,
            help="Limit the audit to one tenant primary key.",
        )
        parser.add_argument(
            "--spu-id",
            type=int,
            help="Limit the audit to one SPU primary key.",
        )

    def _rows_for_spu(self, spu):
        # Prefer the explicit generated_spu relation.  The legacy-code fallback
        # covers imports that were stored before that relation was populated.
        rows = ProductLegacyItem.objects.filter(
            tenant_id=spu.tenant_id,
            generated_spu_id=spu.id,
        ).order_by("id")
        if rows.exists():
            return rows
        if not spu.legacy_spu_code:
            return rows
        return ProductLegacyItem.objects.filter(
            tenant_id=spu.tenant_id,
            legacy_spu_code=spu.legacy_spu_code,
            category_node_id=spu.category_node_id,
        ).order_by("id")

    def handle(self, *args, **options):
        queryset = ProductSPU.objects.filter(legacy_spu_code__gt="").order_by("tenant_id", "id")
        if options.get("tenant_id"):
            queryset = queryset.filter(tenant_id=options["tenant_id"])
        if options.get("spu_id"):
            queryset = queryset.filter(pk=options["spu_id"])

        apply_changes = bool(options.get("apply"))
        mode = "APPLY" if apply_changes else "DRY-RUN"
        planned = 0
        changed = 0
        skipped = 0
        self.stdout.write(f"normalize_spu_product_names mode={mode}")

        context = transaction.atomic() if apply_changes else _null_context()
        with context:
            for spu in queryset.iterator():
                rows = self._rows_for_spu(spu)
                # Tenant-defined display names are stronger evidence than the
                # global standard color dictionary.  An imported code such as
                # ``green`` may be displayed as ``果绿`` by one tenant; pass
                # that alias through so the command removes the complete
                # explicit variant rather than only the generic ``绿`` token.
                color_name_by_code = {
                    str(code): name
                    for code, name in ProductColor.objects.filter(
                        tenant_id=spu.tenant_id,
                        is_active=True,
                    ).values_list("code", "name")
                    if code and name
                }
                desired, evidence = consensus_spu_product_name(
                    rows,
                    color_name_by_code=color_name_by_code,
                )
                if not desired:
                    skipped += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"SKIP tenant={spu.tenant_id} spu={spu.id} code={spu.spu_code} "
                            f"reason={evidence.get('reason', 'no_reliable_candidate')}"
                        )
                    )
                    continue
                if desired == spu.product_name:
                    self.stdout.write(
                        f"OK tenant={spu.tenant_id} spu={spu.id} code={spu.spu_code} name={spu.product_name!r}"
                    )
                    continue

                planned += 1
                self.stdout.write(
                    f"PLAN tenant={spu.tenant_id} spu={spu.id} code={spu.spu_code} "
                    f"before={spu.product_name!r} after={desired!r} "
                    f"rows={evidence.get('rows', 0)} support={evidence.get('support', 0)}"
                )
                if apply_changes:
                    # Deliberately update only the SPU name.  No SKU or legacy
                    # item fields are included in update_fields.
                    spu.product_name = desired
                    spu.save(update_fields=["product_name", "updated_at"])
                    changed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Completed mode={mode}: planned={planned}, changed={changed}, skipped={skipped}."
            )
        )


class _null_context:
    """Small context manager avoiding a transaction for the default dry-run."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

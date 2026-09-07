import django.db.models.deletion
from django.db import migrations, models


def link_existing_product_mappings(apps, schema_editor):
    """Link unambiguous legacy mappings to the canonical detail snapshot.

    Legacy rows are deliberately left nullable when identity fields do not
    match exactly.  A migration must never silently replace a platform or
    SKU identity while repairing the relationship.
    """

    MarketplaceProductMapping = apps.get_model("integrations", "MarketplaceProductMapping")
    PlatformProductDetail = apps.get_model("listings", "PlatformProductDetail")

    details = {}
    for detail in PlatformProductDetail.objects.select_related("platform").all().iterator():
        platform_values = {
            str(detail.platform.platform_type or "").strip().lower(),
            str(detail.platform.code or "").strip().lower(),
        }
        key = (
            detail.tenant_id,
            detail.store_id,
            detail.platform_variant_id,
        )
        for platform in platform_values:
            if platform:
                details.setdefault((key[0], platform, key[1], key[2]), []).append(detail)

    used_detail_ids = set(
        MarketplaceProductMapping.objects.exclude(platform_detail_id=None)
        .values_list("platform_detail_id", flat=True)
    )
    # Count every legacy claim for a canonical detail before applying
    # identity/SKU compatibility checks.  A conflicting row must still block
    # the otherwise compatible row; choosing the latter would silently pick a
    # winner among historical decisions.
    claims = {}
    for mapping in MarketplaceProductMapping.objects.select_related("store_mapping").filter(
        platform_detail_id=None,
    ).iterator():
        matches = details.get(
            (
                mapping.tenant_id,
                str(mapping.platform or "").strip().lower(),
                mapping.store_mapping.store_id,
                mapping.platform_variant_id,
            ),
            [],
        )
        if len(matches) != 1:
            continue
        detail = matches[0]
        claims.setdefault(detail.id, []).append((mapping, detail))

    candidates = {}
    for detail_id, claimed in claims.items():
        if len(claimed) != 1:
            continue
        mapping, detail = claimed[0]
        if mapping.platform_product_id and detail.platform_product_id and mapping.platform_product_id != detail.platform_product_id:
            continue
        if mapping.platform_sku and detail.platform_sku and mapping.platform_sku != detail.platform_sku:
            continue
        # The canonical detail must already carry the same SKU identity.  In
        # particular, never link a historical mapped decision to a detail
        # whose internal SKU is NULL: that would make the UI appear
        # authoritative while losing the confirmed SKU on the fact record.
        if mapping.sku_id != detail.internal_sku_id:
            continue
        if mapping.status == "mapped" and (mapping.sku_id is None or detail.internal_sku_id is None):
            continue
        candidates[detail_id] = mapping
    updates = []
    for detail_id, mapping in candidates.items():
        if detail_id in used_detail_ids:
            continue
        mapping.platform_detail_id = detail_id
        updates.append(mapping)
        used_detail_ids.add(detail_id)
    if updates:
        MarketplaceProductMapping.objects.bulk_update(updates, ["platform_detail"])


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0021_sync_alert_incident"),
        ("listings", "0003_platformproductdetail"),
    ]

    operations = [
        migrations.AddField(
            model_name="marketplaceproductmapping",
            name="platform_detail",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="marketplace_mapping",
                to="listings.platformproductdetail",
            ),
        ),
        migrations.RunPython(link_existing_product_mappings, migrations.RunPython.noop),
    ]

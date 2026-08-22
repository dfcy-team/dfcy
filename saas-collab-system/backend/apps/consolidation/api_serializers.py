"""Strict JSON serializers and redacted DTOs for consolidation APIs."""

from rest_framework import serializers

from apps.packing.serializers import StrictSerializer


class SiteCreateSerializer(StrictSerializer):
    site_code = serializers.CharField(min_length=1, max_length=80, trim_whitespace=True)
    name = serializers.CharField(min_length=1, max_length=160, trim_whitespace=True)
    region_code = serializers.CharField(min_length=1, max_length=80, trim_whitespace=True)
    country_code = serializers.CharField(required=False, allow_blank=True, max_length=8)
    province_state = serializers.CharField(required=False, allow_blank=True, max_length=80)
    city = serializers.CharField(required=False, allow_blank=True, max_length=80)
    district = serializers.CharField(required=False, allow_blank=True, max_length=80)
    address_line = serializers.CharField(required=False, allow_blank=True, max_length=255)
    postal_code = serializers.CharField(required=False, allow_blank=True, max_length=32)
    timezone = serializers.CharField(required=False, allow_blank=True, max_length=64)
    contact_name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    contact_phone = serializers.CharField(required=False, allow_blank=True, max_length=32)
    delivery_instructions = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    effective_from = serializers.DateTimeField(required=False, allow_null=True)
    effective_to = serializers.DateTimeField(required=False, allow_null=True)


class SiteUpdateSerializer(SiteCreateSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    site_code = serializers.CharField(required=False, min_length=1, max_length=80, trim_whitespace=True)
    name = serializers.CharField(required=False, min_length=1, max_length=160, trim_whitespace=True)
    region_code = serializers.CharField(required=False, min_length=1, max_length=80, trim_whitespace=True)


class ConsolidationCreateSerializer(StrictSerializer):
    site_id = serializers.IntegerField(min_value=1)
    consolidation_no = serializers.CharField(required=False, allow_blank=True, max_length=80)
    region_code = serializers.CharField(required=False, allow_blank=True, max_length=80)
    collection_cutoff_at = serializers.DateTimeField(required=False, allow_null=True)
    expected_dispatch_at = serializers.DateTimeField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    external_forwarder_ref = serializers.CharField(required=False, allow_blank=True, max_length=128)
    external_groupage_ref = serializers.CharField(required=False, allow_blank=True, max_length=128)


class ConsolidationUpdateSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    site_id = serializers.IntegerField(required=False, min_value=1)
    region_code = serializers.CharField(required=False, min_length=1, max_length=80, trim_whitespace=True)
    collection_cutoff_at = serializers.DateTimeField(required=False, allow_null=True)
    expected_dispatch_at = serializers.DateTimeField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    external_forwarder_ref = serializers.CharField(required=False, allow_blank=True, max_length=128)
    external_groupage_ref = serializers.CharField(required=False, allow_blank=True, max_length=128)


class BoxesActionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    box_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=False, max_length=500)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate_box_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Box IDs must not contain duplicates.")
        return sorted(value)


class AllocationActionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    exception_code = serializers.CharField(required=False, allow_blank=True, max_length=40)


class SimpleAllocationActionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class ExceptionActionSerializer(SimpleAllocationActionSerializer):
    exception_code = serializers.CharField(required=False, allow_blank=True, max_length=40)


class HandoverSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    release_version = serializers.IntegerField(min_value=1)
    evidence_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=9)
    handover_method = serializers.CharField(min_length=1, max_length=40, trim_whitespace=True)
    handover_reference = serializers.CharField(min_length=1, max_length=128, trim_whitespace=True)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate_evidence_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Evidence IDs must be unique.")
        return sorted(value)


class TransferSerializer(StrictSerializer):
    """Typed transfer handshake; ``expected_version`` is shipment version."""

    shipment_id = serializers.IntegerField(min_value=1)
    expected_version = serializers.IntegerField(min_value=1)
    allocation_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=500)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate_allocation_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Allocation IDs must not contain duplicates.")
        return sorted(value)


class SupplierCapabilitySerializer(StrictSerializer):
    supplier_id = serializers.IntegerField(min_value=1)
    can_submit_handover = serializers.BooleanField()
    expected_version = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)


def site_dto(site, *, internal=True, supplier=False):
    data = {
        "id": site.id, "site_code": site.site_code, "name": site.name,
        "region_code": site.region_code, "country_code": site.country_code,
        "province_state": site.province_state, "city": site.city,
        "district": site.district, "address_line": site.address_line,
        "postal_code": site.postal_code, "timezone": site.timezone,
        "contact_name": site.contact_name if (internal or supplier) else "",
        "contact_phone": site.contact_phone if (internal or supplier) else "",
        "delivery_instructions": site.delivery_instructions if (internal or supplier) else "",
        "is_active": site.is_active, "effective_from": site.effective_from,
        "effective_to": site.effective_to, "version": site.version,
    }
    return data


def allocation_dto(item, *, internal=True):
    data = {
        "id": item.id, "box_id": item.box_id, "box_no": item.box_no_snapshot,
        "quantity": item.quantity_snapshot, "weight": item.weight_snapshot,
        "volume": item.volume_snapshot, "state": item.state, "version": item.version,
        "supplier_id": item.supplier_id_snapshot, "order_ids": list(item.order_ids_snapshot or []),
        "order_nos": list(item.order_nos_snapshot or []), "batch_id": item.batch_id_snapshot,
        "batch_no": item.batch_no_snapshot, "evidence_ids": list(item.evidence_ids or []),
        "handover_method": item.handover_method, "handover_reference": item.handover_reference,
    }
    if internal:
        data["snapshot"] = dict(item.snapshot or {})
        data["created_by_id"] = item.created_by_id
        data["submitted_by_id"] = item.submitted_by_id
    return data


def consolidation_dto(item, *, internal=True):
    allocations = list(item.allocations.all())
    return {
        "id": item.id, "consolidation_no": item.consolidation_no,
        "region_code": item.region_code, "site": site_dto(item.site, internal=internal),
        "status": item.status, "version": item.version,
        "collection_cutoff_at": item.collection_cutoff_at,
        "expected_dispatch_at": item.expected_dispatch_at,
        "note": item.note if internal else "",
        "allocations": [allocation_dto(a, internal=internal) for a in allocations if a.state != "released"],
        "release_site_snapshot": item.release_site_snapshot if internal else {},
        "release_allocation_snapshot": item.release_allocation_snapshot if internal else [],
    }


def supplier_assignment_dto(allocation):
    """Return one supplier's assignment without co-located supplier data."""
    consolidation = allocation.consolidation
    site = consolidation.site
    # Evidence IDs are deliberately derived from the current release binding
    # and reduced to ``id``/``state`` only.  The frozen ``evidence_ids`` field
    # records a prior handover; suppliers need the separate accepted set for
    # their first submission without receiving hashes or internal bindings.
    accepted_evidence = []
    try:
        from apps.files.models import ControlledAttachment
        release_event = consolidation.events.filter(action="release").order_by("-source_version", "-id").first()
        release_version = int(release_event.source_version) if release_event and release_event.source_version else None
        if release_version:
            accepted_evidence = list(
                ControlledAttachment.objects.filter(
                    tenant=allocation.tenant,
                    business_type="consolidation_handover",
                    business_id=str(allocation.id),
                    business_version=release_version,
                    owner_type="supplier",
                    owner_id=allocation.supplier_id_snapshot,
                    state=ControlledAttachment.State.ACCEPTED,
                ).order_by("id").values("id", "state")
            )
    except Exception:
        # DTO generation must fail closed if evidence storage is unavailable;
        # the supplier can still view assignment metadata but cannot submit.
        accepted_evidence = []
    allocation_data = allocation_dto(allocation, internal=False)
    allocation_data["accepted_evidence_ids"] = [int(item["id"]) for item in accepted_evidence]
    allocation_data["accepted_evidence"] = [
        {"id": int(item["id"]), "state": str(item["state"])} for item in accepted_evidence
    ]
    return {
        "allocation": allocation_data,
        "consolidation": {
            "id": consolidation.id,
            "consolidation_no": consolidation.consolidation_no,
            "region_code": consolidation.region_code,
            "site": site_dto(site, internal=False, supplier=True),
            "status": consolidation.status,
            "version": consolidation.version,
            "collection_cutoff_at": consolidation.collection_cutoff_at,
            "expected_dispatch_at": consolidation.expected_dispatch_at,
        },
    }


def supplier_capability_dto(capability):
    return {
        "id": capability.id,
        "supplier_id": capability.supplier_id,
        "can_submit_handover": capability.can_submit_handover,
        "version": capability.version,
    }

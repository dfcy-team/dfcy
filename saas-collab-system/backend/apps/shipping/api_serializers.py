"""Strict input serializers and redacted shipment DTOs."""

from rest_framework import serializers

from apps.packing.serializers import StrictSerializer


class ShipmentCreateSerializer(StrictSerializer):
    shipment_no = serializers.CharField(min_length=1, max_length=80, trim_whitespace=True)
    region_code = serializers.CharField(min_length=1, max_length=80, trim_whitespace=True)
    origin_site_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    origin_site_snapshot = serializers.JSONField(required=False)
    destination_country_code = serializers.CharField(required=False, allow_blank=True, max_length=8)
    destination_port_code = serializers.CharField(required=False, allow_blank=True, max_length=32)
    destination_warehouse_code = serializers.CharField(required=False, allow_blank=True, max_length=64)
    note = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    planned_dispatch_at = serializers.DateTimeField(required=False, allow_null=True)
    forwarder_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
    groupage_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
    container_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
    transport_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)


class ShipmentUpdateSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    region_code = serializers.CharField(required=False, min_length=1, max_length=80, trim_whitespace=True)
    origin_site_id_snapshot = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    origin_site_snapshot = serializers.JSONField(required=False)
    destination_country_code = serializers.CharField(required=False, allow_blank=True, max_length=8)
    destination_port_code = serializers.CharField(required=False, allow_blank=True, max_length=32)
    destination_warehouse_code = serializers.CharField(required=False, allow_blank=True, max_length=64)
    note = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    planned_dispatch_at = serializers.DateTimeField(required=False, allow_null=True)
    forwarder_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
    groupage_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
    container_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
    transport_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class ShipmentBoxesSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    consolidation_id = serializers.IntegerField(min_value=1)
    allocation_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=500)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate_allocation_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Allocation IDs must not contain duplicates.")
        return sorted(value)


class ShipmentActionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    customs_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
    allocation_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=False, max_length=500)

    def validate_allocation_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Allocation IDs must not contain duplicates.")
        return sorted(value)


class CustomsActionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    customs_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class DispatchActionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    allocation_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=False, max_length=500)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate_allocation_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Allocation IDs must not contain duplicates.")
        return sorted(value)


class SimpleActionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)


def shipment_allocation_dto(item, *, internal=True):
    data = {
        "id": item.id, "box_id": item.box_id, "box_no": item.box_no_snapshot,
        "quantity": item.quantity_snapshot, "weight": item.weight_snapshot,
        "volume": item.volume_snapshot, "state": item.state, "version": item.version,
        "supplier_id": item.supplier_id_snapshot, "order_ids": list(item.order_ids_snapshot or []),
        "order_nos": list(item.order_nos_snapshot or []), "batch_id": item.batch_id_snapshot,
        "batch_no": item.batch_no_snapshot, "consolidation_id": item.consolidation_id,
    }
    if internal:
        data.update({"source_release_version": item.source_release_version, "source_consolidation_version": item.source_consolidation_version, "created_by_id": item.created_by_id})
    return data


def shipment_dto(item, *, internal=True):
    return {
        "id": item.id, "shipment_no": item.shipment_no, "route_type": item.route_type,
        "region_code": item.region_code, "origin_site_id": item.origin_site_id_snapshot,
        "origin_site": dict(item.origin_site_snapshot or {}),
        "destination_country_code": item.destination_country_code,
        "destination_port_code": item.destination_port_code,
        "destination_warehouse_code": item.destination_warehouse_code,
        "status": item.status, "version": item.version,
        "planned_dispatch_at": item.planned_dispatch_at,
        "actual_dispatch_at": item.actual_dispatch_at,
        "port_arrived_at": item.port_arrived_at,
        "warehouse_arrived_at": item.warehouse_arrived_at,
        "cleared_at": item.cleared_at,
        "customs_reference": item.customs_reference,
        "allocations": [shipment_allocation_dto(a, internal=internal) for a in item.box_allocations.all()],
        "note": item.note if internal else "",
        "forwarder_reference": item.forwarder_reference if internal else "",
        "groupage_reference": item.groupage_reference if internal else "",
        "container_reference": item.container_reference if internal else "",
        "transport_reference": item.transport_reference if internal else "",
    }

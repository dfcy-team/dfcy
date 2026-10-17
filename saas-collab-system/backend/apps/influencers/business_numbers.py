"""Tenant-scoped allocation and aliases; writers must already hold the tenant lock."""
import re
from itertools import chain

from rest_framework.exceptions import ValidationError

from .models import InfluencerNumberReservation, OutreachTask, SampleFulfillment


def number_spec(namespace):
    return {"task": (OutreachTask, "task_no", "task"),
            "sample": (SampleFulfillment, "fulfillment_no", "sample"),
            "type": (SampleFulfillment, "type_no", "sample")}[namespace]


def reserved_owner(tenant_id, namespace, number):
    owner_field = number_spec(namespace)[2]
    row = InfluencerNumberReservation.objects.select_related(owner_field).filter(
        tenant_id=tenant_id, namespace=namespace, number__iexact=number,
    ).first()
    return getattr(row, owner_field) if row else None


def reserve_number(instance, namespace, number):
    model, field, owner_field = number_spec(namespace)
    number = str(number or "").strip()
    if not number or len(number) > 80:
        raise ValidationError({field: "Business number must be 1-80 characters."})
    if model.objects.filter(tenant_id=instance.tenant_id, **{field + "__iexact": number}).exclude(pk=instance.pk).exists():
        raise ValidationError({field: "Business number is already in use."}, code="conflict")
    if namespace == "type":
        legacy_rows = SampleFulfillment.objects.filter(
            tenant_id=instance.tenant_id, fulfillment_no__iexact=number,
        ).exclude(pk=instance.pk).values_list("fulfillment_no", "link_type")
        if any(re.fullmatch(re.escape(link_type or "") + r"\d+", fulfillment_no or "", flags=re.IGNORECASE)
               for fulfillment_no, link_type in legacy_rows):
            raise ValidationError({field: "Business number is reserved by a legacy fulfillment number."}, code="conflict")
    row = InfluencerNumberReservation.objects.filter(
        tenant_id=instance.tenant_id, namespace=namespace, number__iexact=number,
    ).first()
    if row is None:
        row = InfluencerNumberReservation.objects.create(
            tenant_id=instance.tenant_id, namespace=namespace, number=number, **{owner_field: instance},
        )
    if getattr(row, owner_field + "_id") != instance.pk:
        raise ValidationError({field: "Business number is reserved by another record."}, code="conflict")


def next_number(tenant, namespace, prefix, *, width=4):
    model, field, _ = number_spec(namespace)
    numbers = chain(
        model.objects.filter(tenant=tenant, **{field + "__istartswith": prefix}).values_list(field, flat=True),
        InfluencerNumberReservation.objects.filter(
            tenant=tenant, namespace=namespace, number__istartswith=prefix,
        ).values_list("number", flat=True),
    )
    highest = 0
    for number in numbers:
        match = re.fullmatch(re.escape(prefix) + r"(\d+)", number or "", flags=re.IGNORECASE)
        if match:
            highest = max(highest, int(match.group(1)))
    if namespace == "type":
        legacy_rows = SampleFulfillment.objects.filter(
            tenant=tenant, fulfillment_no__istartswith=prefix, link_type__iexact=prefix,
        ).values_list("fulfillment_no", "link_type")
        for number, link_type in legacy_rows:
            if match := re.fullmatch(re.escape(link_type) + r"(\d+)", number or "", flags=re.IGNORECASE):
                highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1:0{width}d}"


def reserve_current(instance):
    if isinstance(instance, OutreachTask):
        reserve_number(instance, "task", instance.task_no)
    else:
        reserve_number(instance, "sample", instance.fulfillment_no)
        if instance.type_no:
            reserve_number(instance, "type", instance.type_no)

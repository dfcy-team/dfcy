"""Persist Feishu finance completion data as payment request evidence.

This module deliberately records evidence only. It never creates a PaymentRecord.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.integrations.feishu_finance_form import parse_finance_form, validate_finance_file
from apps.integrations.models import FeishuIdentity
from apps.permissions.services import user_has_finance_permission, check_user_permission
from apps.supply_chain.models import domain_write
from apps.tenants.models import Tenant
from apps.supply_chain.payment_request_models import (
    SupplyPaymentBatch, SupplyPaymentBatchVoucher, SupplyPaymentRequest,
    SupplyPaymentRequestVoucher,
)
from apps.workflows.services import write_workflow_audit
from .feishu_approval_models import FeishuFinanceHandoff


def finance_ready(instance, authoritative):
    """Return true only when authoritative data confirms the assigned finance task."""
    snapshot = instance.finance_snapshot or {}
    if not snapshot or str(authoritative.get("status", "")).upper() != "APPROVED" or authoritative.get("reverted") is True:
        return False
    tasks = authoritative.get("task_list")
    if not isinstance(tasks, list):
        return False
    return any(
        isinstance(task, dict)
        and str(task.get("node_id", "")) == str(snapshot.get("node_id", ""))
        and task.get("open_id") == snapshot.get("handler_open_id")
        and str(task.get("status", "")).upper() in {"APPROVED", "DONE"}
        for task in tasks
    )


def _handler(instance):
    snap = instance.finance_snapshot or {}
    handler_id = snap.get("handler_id")
    handler = get_user_model().objects.filter(pk=handler_id, tenant_id=instance.tenant_id, is_active=True, user_type="internal").first() if handler_id else None
    if not handler or handler.tenant_id != instance.tenant_id:
        raise ValueError("finance handler is invalid")
    identity = FeishuIdentity.objects.filter(tenant_id=instance.tenant_id, user=handler, status="active").first()
    if not identity or identity.open_id != snap.get("handler_open_id"):
        raise ValueError("finance handler identity mismatch")
    if not (check_user_permission(handler, "supply.v2.manage") and user_has_finance_permission(handler, "finance.reconcile")):
        raise ValueError("finance handler lacks required permissions")
    return handler


def _business_parent(instance):
    approval = instance.approval
    if approval.tenant_id != instance.tenant_id:
        raise ValueError("approval tenant mismatch")
    if approval.business_type == "supply_payment_request":
        parent = SupplyPaymentRequest.objects.select_for_update().filter(
            tenant_id=instance.tenant_id, pk=approval.business_id,
            approval=approval, status="submitted", payment__isnull=True,
        ).first()
    elif approval.business_type == "supply_payment_batch":
        parent = SupplyPaymentBatch.objects.select_for_update().filter(
            tenant_id=instance.tenant_id, pk=approval.business_id,
            approval=approval, status="submitted",
        ).first()
    else:
        parent = None
    if not parent:
        raise ValueError("finance approval has no eligible submitted payment request")
    return parent


def _stable_key(instance, source_key):
    digest = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
    return "feishu:" + hashlib.sha256(f"{instance.pk}:{digest}".encode()).hexdigest()


def sync_finance_handoff(instance, authoritative, downloaded_files):
    """Atomically save actual payment date and validated voucher bytes; idempotent."""
    if not finance_ready(instance, authoritative):
        raise ValueError("finance task is not complete")
    snapshot = instance.finance_snapshot or {}
    parsed = parse_finance_form(
        authoritative.get("form", authoritative), date_widget_id=snapshot.get("date_widget_id"),
        voucher_widget_id=snapshot.get("voucher_widget_id"),
    )
    declared = {f["source_key"]: f for f in parsed["files"]}
    incoming = list(downloaded_files or [])
    if not incoming or len(incoming) > 20 or len(declared) != len(parsed["files"]):
        raise ValueError("voucher source list is invalid")
    received = {}
    for item in incoming:
        key = item.get("source_key")
        if key not in declared or key in received:
            raise ValueError("downloaded vouchers do not match the submitted form")
        if item.get("file_name") != declared[key]["name"]:
            raise ValueError("downloaded voucher filename does not match the submitted form")
        meta = validate_finance_file(item.get("content"), declared_name=item.get("file_name"), content_type=item.get("media_type"))
        if item.get("byte_size") != meta["byte_size"] or item.get("sha256") != meta["sha256"]:
            raise ValueError("downloaded voucher metadata mismatch")
        received[key] = (item, meta)
    if set(received) != set(declared):
        raise ValueError("downloaded vouchers do not match the submitted form")

    handler = _handler(instance)
    with transaction.atomic():
        # Caller may already hold the tenant lock. Reacquiring it is safe and keeps
        # this entry point correct when invoked independently.
        Tenant.objects.select_for_update().get(pk=instance.tenant_id)
        locked_instance = type(instance).objects.select_for_update().select_related("approval").get(pk=instance.pk, tenant_id=instance.tenant_id)
        approval = type(locked_instance.approval).objects.select_for_update().get(pk=locked_instance.approval_id, tenant_id=instance.tenant_id)
        # A confirmation can finish while the HTTPS download is in flight.
        # Under the tenant lock, a linked posted request needs no new evidence.
        model = SupplyPaymentRequest if approval.business_type == "supply_payment_request" else SupplyPaymentBatch
        posted = model.objects.select_for_update().filter(tenant_id=instance.tenant_id, pk=approval.business_id, approval=approval, status="paid").exists()
        if posted:
            existing = FeishuFinanceHandoff.objects.filter(instance=locked_instance, tenant_id=instance.tenant_id, status="received").first()
            if existing is None:
                raise ValueError("posted payment has no verified finance handoff")
            return existing
        parent = _business_parent(locked_instance)
        handoff, _ = FeishuFinanceHandoff.objects.select_for_update().get_or_create(
            instance=locked_instance, defaults={"tenant_id": locked_instance.tenant_id, "handler": handler}
        )
        if handoff.tenant_id != locked_instance.tenant_id or handoff.handler_id != handler.pk:
            raise ValueError("finance handoff ownership mismatch")
        manifest = []
        for key in sorted(received):
            item, meta = received[key]
            manifest.append({"source_key_hash": hashlib.sha256(key.encode()).hexdigest(), "file_name": meta["filename"], "media_type": meta["media_type"], "byte_size": meta["byte_size"], "sha256": meta["sha256"]})
        digest = hashlib.sha256(json.dumps({"date": parsed["actual_payment_date"].isoformat(), "files": manifest}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if handoff.status == "received":
            if handoff.content_hash == digest:
                return handoff
            handoff.status = "needs_review"
            handoff.last_error = "finance_data_changed"
            handoff.save(update_fields=["status", "last_error", "updated_at"])
            write_workflow_audit(approval, resource_type="approval", actor=handler, action="finance_handoff_conflict", to_status="needs_review", detail={"source": "feishu_finance_handoff", "content_hash": digest})
            return handoff
        if handoff.status == "needs_review":
            return handoff
        existing = SupplyPaymentRequestVoucher.objects.filter(tenant_id=parent.tenant_id, request_id=parent.pk).count() if isinstance(parent, SupplyPaymentRequest) else SupplyPaymentBatchVoucher.objects.filter(tenant_id=parent.tenant_id, batch_id=parent.pk).count()
        if existing + len(received) > 20:
            raise ValueError("voucher limit exceeded")
        with domain_write():
            for key, (item, meta) in received.items():
                fields = dict(tenant_id=parent.tenant_id, created_by=handler, file_name=meta["filename"], media_type=meta["media_type"], byte_size=meta["byte_size"], sha256=meta["sha256"], idempotency_key=_stable_key(locked_instance, key), content=bytes(item["content"]))
                if isinstance(parent, SupplyPaymentRequest):
                    SupplyPaymentRequestVoucher.objects.get_or_create(request=parent, idempotency_key=fields["idempotency_key"], defaults=fields)
                else:
                    SupplyPaymentBatchVoucher.objects.get_or_create(batch=parent, idempotency_key=fields["idempotency_key"], defaults=fields)
        handoff.actual_payment_date = parsed["actual_payment_date"]
        handoff.voucher_manifest = manifest
        handoff.content_hash = digest
        handoff.status = "received"
        handoff.last_error = ""
        handoff.received_at = timezone.now()
        handoff.save()
        write_workflow_audit(approval, resource_type="approval", actor=handler, action="finance_handoff_received", to_status="received", detail={"source": "feishu_finance_handoff", "voucher_count": len(manifest), "content_hash": digest})
        return handoff


def finance_data(approval):
    instance = getattr(approval, "feishu_native", None)
    if not instance or not instance.finance_snapshot:
        return None
    handoff = getattr(instance, "finance_handoff", None)
    if not handoff:
        return {"status": "needs_review" if instance.status == "manual_review" else "awaiting_finance", "actual_payment_date": None, "vouchers": []}
    return {"status": handoff.status, "actual_payment_date": handoff.actual_payment_date.isoformat() if handoff.actual_payment_date else None, "vouchers": [{k: v for k, v in item.items() if k != "source_key_hash"} for item in handoff.voucher_manifest]}


def assert_finance_postable(actor, approval, payload, authoritative=None):
    """Gate actual posting for native finance approvals; legacy approvals pass through."""
    instance = getattr(approval, "feishu_native", None)
    if not instance or not instance.finance_snapshot:
        return True
    if not isinstance(authoritative, dict) or not finance_ready(instance, authoritative):
        raise ValueError("authoritative finance approval is unavailable")
    snapshot = instance.finance_snapshot
    current = parse_finance_form(
        authoritative.get("form", authoritative),
        date_widget_id=snapshot.get("date_widget_id"),
        voucher_widget_id=snapshot.get("voucher_widget_id"),
    )
    handoff = getattr(instance, "finance_handoff", None)
    if not handoff or handoff.status != "received" or handoff.handler_id != actor.pk:
        raise ValueError("finance handoff is not postable")
    paid_date = payload.get("date", payload.get("actual_payment_date", payload.get("payment_date"))) if isinstance(payload, dict) else None
    if isinstance(paid_date, str):
        try:
            paid_date = date.fromisoformat(paid_date)
        except ValueError:
            pass
    if paid_date != handoff.actual_payment_date:
        raise ValueError("posted payment date must match Feishu finance date")
    declared = {
        hashlib.sha256(item["source_key"].encode("utf-8")).hexdigest(): item
        for item in current["files"]
    }
    saved = {item.get("source_key_hash"): item for item in handoff.voucher_manifest}
    if (current["actual_payment_date"] != handoff.actual_payment_date or not declared
            or set(declared) != set(saved)
            or any(declared[key]["name"] != item.get("file_name") for key, item in saved.items())):
        raise ValueError("authoritative finance form changed after handoff")
    # A provider may reuse a file token while replacing its bytes. Re-download
    # through the bounded, host-pinned helper and compare content digests before
    # allowing posting. This is read-only and uses URLs from this same response.
    from .feishu_finance_download import download_finance_file
    for key, item in declared.items():
        current_file = download_finance_file(
            item, allowed_hosts=snapshot.get("attachment_hosts", [])
        )
        stored = saved[key]
        if (current_file.get("sha256") != stored.get("sha256")
                or current_file.get("byte_size") != stored.get("byte_size")
                or current_file.get("media_type") != stored.get("media_type")):
            raise ValueError("authoritative finance voucher bytes changed after handoff")
    from apps.supply_chain.payment_request_models import active_vouchers
    if approval.business_type == 'supply_payment_request':
        parent=SupplyPaymentRequest.objects.filter(tenant_id=approval.tenant_id,approval=approval).first()
    else:
        parent=SupplyPaymentBatch.objects.filter(tenant_id=approval.tenant_id,approval=approval).first()
    if parent is None:raise ValueError('finance business source missing')
    actual = {}
    for voucher in active_vouchers(parent.vouchers.all()):
        content = bytes(voucher.content)
        digest = hashlib.sha256(content).hexdigest()
        if digest != voucher.sha256 or voucher.idempotency_key in actual:
            raise ValueError('finance voucher bytes changed')
        actual[voucher.idempotency_key] = digest
    expected={"feishu:"+hashlib.sha256(f"{instance.pk}:{v['source_key_hash']}".encode()).hexdigest():v['sha256'] for v in handoff.voucher_manifest}
    if not expected or actual != expected:raise ValueError('finance voucher set changed')
    return True


def finance_payload(approval, payload):
    result = payload.copy()
    data = finance_data(approval) if approval else None
    if data and data['status'] == 'received' and not result.get('date'):
        result['date'] = data['actual_payment_date']
    return result


def require_finance_postable(actor, approval, payload, *, authoritative=None):
    from rest_framework.exceptions import ValidationError
    try:
        instance = getattr(approval, "feishu_native", None)
        if instance and instance.finance_snapshot and authoritative is None:
            from apps.integrations.feishu_native_approval import ensure_native_postable
            authoritative = ensure_native_postable(approval)
        elif not (instance and instance.finance_snapshot):
            authoritative = None
        assert_finance_postable(actor, approval, payload, authoritative)
        return authoritative
    except ValueError:
        raise ValidationError('财务回传资料未核验完成、办理人不匹配或实付日期已变化，暂不能入账。')

import hashlib
import json
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone

from apps.audit.services import write_operation_log
from apps.common.exceptions import StateConflict, VersionConflict

from .models import (
    PackingBatch,
    PackingBox,
    PackingEvent,
    _packing_domain_write_context,
)


QR_SCHEMA_VERSION = "sc-f2-packing-qr-v1"
LABEL_SCHEMA_VERSION = "sc-f2-label-snapshot-v1"
LAYOUT_VERSION = "packing-label-v1"
RENDERER_VERSION = "sc-f2-reportlab-v1"
FONT_BUNDLE_DIGEST = hashlib.sha256(b"Helvetica|Helvetica-Bold").hexdigest()


def _canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _decimal(value):
    return None if value is None else format(value, "f")


def _event_time():
    return timezone.now().isoformat().replace("+00:00", "Z")


def _box_snapshot(batch, box):
    items = [
        {
            "order_no": item.order_no_snapshot,
            "sku_code": item.sku_code_snapshot,
            "product_name": item.product_name_snapshot,
            "quantity": item.quantity,
        }
        for item in sorted(
            box.items.all(),
            key=lambda item: (
                item.order_no_snapshot,
                item.sku_code_snapshot,
                item.product_name_snapshot,
            ),
        )
    ]
    content = {
        "box_no": box.box_no,
        "sequence": box.sequence,
        "weight": _decimal(box.weight),
        "volume": _decimal(box.volume),
        "items": items,
    }
    digest = hashlib.sha256(_canonical_bytes(content)).hexdigest()
    qr_payload = {
        "schema_version": QR_SCHEMA_VERSION,
        "batch_no": batch.batch_no,
        "box_no": box.box_no,
        "packing_version": batch.version,
        "standard_code": batch.standard_version.code,
        "standard_version": str(batch.standard_version.version),
        "content_digest": digest,
    }
    return {**content, "content_digest": digest, "qr_payload": qr_payload}


def create_label_snapshot(
    *,
    batch_id,
    actor,
    idempotency_key,
    request_hash,
    expected_version,
    box_id=None,
):
    batch = (
        PackingBatch.objects.select_for_update()
        .select_related("standard_version")
        .prefetch_related("boxes__items")
        .get(pk=batch_id, tenant=actor.tenant)
    )
    if batch.version != expected_version:
        raise VersionConflict("Packing batch version is stale.")
    if batch.status not in {
        PackingBatch.Status.IN_PROGRESS,
        PackingBatch.Status.COMPLETED,
    }:
        raise StateConflict("Labels require an in-progress or completed packing batch.")
    boxes = sorted(batch.boxes.all(), key=lambda item: item.sequence)
    if box_id is not None:
        boxes = [box for box in boxes if box.id == box_id]
        if not boxes:
            raise StateConflict("The requested box is not available for this batch.")
    if not boxes or any(not list(box.items.all()) for box in boxes):
        raise StateConflict("Labels require non-empty packing boxes.")

    event_time = _event_time()
    label_scope = "box" if box_id is not None else "batch"
    filename = (
        f"{boxes[0].box_no}-v{batch.version}.pdf"
        if box_id is not None
        else f"{batch.batch_no}-v{batch.version}.pdf"
    )
    snapshot = {
        "schema_version": LABEL_SCHEMA_VERSION,
        "label_scope": label_scope,
        "event_time": event_time,
        "batch_no": batch.batch_no,
        "packing_version": batch.version,
        "standard": {
            "code": batch.standard_version.code,
            "version": str(batch.standard_version.version),
            "title": batch.standard_version.title,
        },
        "layout_version": LAYOUT_VERSION,
        "renderer_version": RENDERER_VERSION,
        "font_bundle_digest": FONT_BUNDLE_DIGEST,
        "filename": filename,
        "boxes": [_box_snapshot(batch, box) for box in boxes],
    }
    with _packing_domain_write_context():
        PackingEvent.objects.create(
            tenant=batch.tenant,
            batch=batch,
            action=PackingEvent.Action.GENERATE_LABEL,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
            actor_type=(
                PackingEvent.ActorType.INTERNAL
                if actor.user_type == "internal"
                else PackingEvent.ActorType.SUPPLIER
            ),
            before_status=batch.status,
            after_status=batch.status,
            batch_version=batch.version,
            payload={"label_scope": label_scope},
            response_snapshot=snapshot,
        )
    write_operation_log(
        tenant=batch.tenant,
        user=actor,
        module="supply_chain",
        action="packing.generate_label",
        object_type="PackingBatch",
        object_id=batch.id,
        before_data={},
        after_data={
            "batch_no": batch.batch_no,
            "packing_version": batch.version,
            "label_scope": label_scope,
            "box_count": len(boxes),
        },
    )
    return snapshot, 200


def _qr_text(payload):
    ordered = {
        "schema_version": payload["schema_version"],
        "batch_no": payload["batch_no"],
        "box_no": payload["box_no"],
        "packing_version": payload["packing_version"],
        "standard_code": payload["standard_code"],
        "standard_version": payload["standard_version"],
        "content_digest": payload["content_digest"],
    }
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))


def render_label_pdf(snapshot, *, status=200):
    try:
        from reportlab.graphics import renderPDF
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("reportlab is required to render packing labels.") from exc

    buffer = BytesIO()
    width, height = 595.2756, 841.8898
    pdf = canvas.Canvas(
        buffer,
        pagesize=(width, height),
        pageCompression=1,
        invariant=1,
    )
    pdf.setAuthor("SC-F2 Packing")
    pdf.setCreator(snapshot["renderer_version"])
    pdf.setTitle(snapshot["filename"])
    pdf.setSubject(snapshot["event_time"])
    for box in snapshot["boxes"]:
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(42, 790, snapshot["batch_no"])
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(42, 755, box["box_no"])
        pdf.setFont("Helvetica", 10)
        pdf.drawString(42, 730, f"Packing version: {snapshot['packing_version']}")
        pdf.drawString(
            42,
            714,
            f"Standard: {snapshot['standard']['code']} v{snapshot['standard']['version']}",
        )
        pdf.drawString(42, 698, f"Event time: {snapshot['event_time']}")
        pdf.drawString(42, 682, f"Weight: {box['weight'] or ''}")
        pdf.drawString(42, 666, f"Volume: {box['volume'] or ''}")
        y = 630
        for item in box["items"]:
            text = (
                f"{item['order_no']} | {item['sku_code']} | "
                f"{item['product_name']} | {item['quantity']}"
            )
            pdf.drawString(42, y, text[:95])
            y -= 16
        qr = QrCodeWidget(_qr_text(box["qr_payload"]))
        bounds = qr.getBounds()
        size = 150
        scale_x = size / (bounds[2] - bounds[0])
        scale_y = size / (bounds[3] - bounds[1])
        drawing = Drawing(size, size, transform=[scale_x, 0, 0, scale_y, 0, 0])
        drawing.add(qr)
        renderPDF.draw(drawing, pdf, width - 200, 620)
        pdf.showPage()
    pdf.save()
    payload = buffer.getvalue()
    event_date = (
        snapshot["event_time"][:19]
        .replace("-", "")
        .replace(":", "")
        .replace("T", "")
    )
    payload = payload.replace(
        b"D:20000101000000+00'00'",
        f"D:{event_date}+00'00'".encode("ascii"),
    )
    digest = hashlib.sha256(payload).hexdigest()
    response = HttpResponse(payload, content_type="application/pdf", status=status)
    response["Content-Disposition"] = f'attachment; filename="{snapshot["filename"]}"'
    response["ETag"] = f'"{digest}"'
    response["X-Packing-Batch-Version"] = str(snapshot["packing_version"])
    response["Cache-Control"] = "private, no-store"
    return response

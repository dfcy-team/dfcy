"""Authenticated upload and download endpoints for settlement proof files."""
import hashlib
from io import BytesIO
from pathlib import PurePath

from PIL import Image, UnidentifiedImageError
from django.db import IntegrityError, transaction
from django.http import FileResponse
from django.utils.http import content_disposition_header
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from . import costs, services
from .models import PaymentVoucher, SettlementRevision, domain_write
from .permissions import MANAGE, VIEW
from .views import InternalAPI
from .api import key

MAX_BYTES = 10 * 1024 * 1024
MAX_PER_REVISION = 20


def _revision(actor, kind, pk, revision_id, permission):
    target = costs.target_for(actor, kind, pk, permission)
    if kind not in {"shipment", "batch"}:
        raise NotFound("结算历史不存在。")
    revision = SettlementRevision.objects.filter(
        pk=revision_id, tenant_id=actor.tenant_id,
        settlement__tenant_id=actor.tenant_id,
        **{f"settlement__{kind}_id": target.pk},
    ).first()
    if revision is None:
        raise NotFound("结算历史不存在或无权访问。")
    return target, revision


def _metadata(voucher):
    return {
        "id": voucher.pk,
        "file_name": voucher.file_name,
        "media_type": voucher.media_type,
        "byte_size": voucher.byte_size,
        "sha256": voucher.sha256,
        "created_at": voucher.created_at,
        "uploaded_by": voucher.created_by.full_name or voucher.created_by.username,
    }


def _validate_file(upload):
    if upload is None or not 0 < int(getattr(upload, "size", 0) or 0) <= MAX_BYTES:
        raise ValidationError("凭证须为非空文件且不超过 10MB。")
    name = PurePath(str(upload.name or "").replace("\\", "/")).name
    if not name or len(name) > 200 or any(ord(char) < 32 for char in name):
        raise ValidationError("凭证文件名无效。")
    extension = PurePath(name).suffix.lower()
    body = upload.read(MAX_BYTES + 1)
    if not body or len(body) > MAX_BYTES:
        raise ValidationError("凭证超过 10MB。")
    if extension == ".pdf":
        if not body.startswith(b"%PDF-") or b"%%EOF" not in body[-2048:]:
            raise ValidationError("PDF 文件内容无效。")
        media_type = "application/pdf"
    elif extension in {".jpg", ".jpeg", ".png"}:
        try:
            with Image.open(BytesIO(body)) as image:
                if image.width * image.height > 25_000_000:
                    raise ValueError()
                expected = "PNG" if extension == ".png" else "JPEG"
                if image.format != expected:
                    raise ValueError()
                image.verify()
        except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise ValidationError("图片内容无效或与扩展名不匹配。") from exc
        media_type = "image/png" if extension == ".png" else "image/jpeg"
    else:
        raise ValidationError("仅支持 PDF、JPG、PNG 凭证。")
    return name, media_type, body, hashlib.sha256(body).hexdigest()


class PaymentVouchers(InternalAPI):
    http_method_names = ["get", "post", "options"]

    def get(self, request, kind, pk, revision_id):
        _, revision = _revision(request.user, kind, pk, revision_id, VIEW)
        vouchers = PaymentVoucher.objects.filter(
            tenant_id=request.user.tenant_id, settlement_revision=revision,
        ).select_related("created_by").defer("content")
        return Response({"data": [_metadata(row) for row in vouchers]})

    def post(self, request, kind, pk, revision_id):
        target, revision = _revision(request.user, kind, pk, revision_id, MANAGE)
        upload = request.FILES.get("file")
        name, media_type, body, digest = _validate_file(upload)
        idem_key = key(request)
        payload = {"revision_id": revision.pk, "file_name": name, "sha256": digest}
        with transaction.atomic():
            services._tenant_lock(request.user)
            replay = services._prior_event(request.user, target, "settlement_voucher_uploaded", idem_key, payload)
            if replay:
                voucher_id = replay.payload.get("payment_voucher_id")
                voucher = PaymentVoucher.objects.filter(
                    tenant_id=request.user.tenant_id, settlement_revision=revision, pk=voucher_id,
                ).select_related("created_by").defer("content").first()
                if voucher is None:
                    raise ValidationError("上传重试记录缺少对应凭证，请联系管理员。")
                return Response({"data": _metadata(voucher)})
            existing = PaymentVoucher.objects.filter(
                tenant_id=request.user.tenant_id, settlement_revision=revision, idempotency_key=idem_key,
            ).defer("content").first()
            if existing:
                if existing.sha256 != digest:
                    raise ValidationError("该幂等键已用于其他凭证，请重新选择文件。")
                return Response({"data": _metadata(existing)})
            if PaymentVoucher.objects.filter(tenant_id=request.user.tenant_id, settlement_revision=revision).count() >= MAX_PER_REVISION:
                raise ValidationError("每条结算历史最多上传20个凭证。")
            try:
                with domain_write():
                    voucher = PaymentVoucher.objects.create(
                        tenant=request.user.tenant, created_by=request.user,
                        settlement_revision=revision, file_name=name, media_type=media_type,
                        byte_size=len(body), sha256=digest, idempotency_key=idem_key, content=body,
                    )
                    services._event(request.user, target, "settlement_voucher_uploaded", idem_key, payload,
                                    audit={"payment_voucher_id": voucher.pk, "settlement_revision_id": revision.pk})
            except IntegrityError:
                raise ValidationError("凭证已被另一个请求保存，请刷新历史记录。")
        return Response({"data": _metadata(voucher)}, status=201)


class PaymentVoucherDownload(InternalAPI):
    http_method_names = ["get", "options"]

    def get(self, request, kind, pk, revision_id, voucher_id):
        _, revision = _revision(request.user, kind, pk, revision_id, VIEW)
        voucher = PaymentVoucher.objects.filter(
            tenant_id=request.user.tenant_id, settlement_revision=revision, pk=voucher_id,
        ).first()
        if voucher is None:
            raise NotFound("结算凭证不存在或无权访问。")
        if hashlib.sha256(bytes(voucher.content)).hexdigest() != voucher.sha256:
            raise ValidationError("凭证完整性校验失败，请联系采购。")
        response = FileResponse(BytesIO(bytes(voucher.content)), as_attachment=True,
                                filename=voucher.file_name, content_type=voucher.media_type)
        response["Content-Disposition"] = content_disposition_header(True, voucher.file_name)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["X-File-SHA256"] = voucher.sha256
        return response


class PaymentRecordVouchers(InternalAPI):
    http_method_names = ["get", "post", "options"]

    def _record(self, request, kind, pk, payment_id, permission):
        from .costs import _payment_owner
        from .cost_models import PaymentRecord
        owner = _payment_owner(request.user, kind, pk, permission)
        owner_filter = {'purchase_order': owner} if kind == 'purchase' else {kind: owner}
        record = PaymentRecord.objects.filter(tenant_id=request.user.tenant_id, pk=payment_id, **owner_filter).first()
        if record is None:
            raise NotFound('付款记录不存在或无权访问。')
        return owner, record

    def get(self, request, kind, pk, payment_id):
        _, record = self._record(request, kind, pk, payment_id, VIEW)
        rows = PaymentVoucher.objects.filter(tenant_id=request.user.tenant_id, payment=record).select_related('created_by').defer('content')
        return Response({'data': [_metadata(row) for row in rows]})

    def post(self, request, kind, pk, payment_id):
        owner, record = self._record(request, kind, pk, payment_id, MANAGE)
        upload = request.FILES.get('file')
        name, media_type, body, digest = _validate_file(upload)
        idem_key = key(request)
        payload = {'payment_id': record.pk, 'file_name': name, 'sha256': digest}
        with transaction.atomic():
            services._tenant_lock(request.user)
            replay = services._prior_event(request.user, record, 'payment_voucher_uploaded', idem_key, payload)
            if replay:
                voucher = PaymentVoucher.objects.filter(tenant_id=request.user.tenant_id, payment=record,
                    pk=replay.payload.get('payment_voucher_id')).select_related('created_by').defer('content').first()
                if voucher is None:
                    raise ValidationError('上传重试记录缺少对应凭证。')
                return Response({'data': _metadata(voucher)})
            if PaymentVoucher.objects.filter(tenant_id=request.user.tenant_id, payment=record).count() >= MAX_PER_REVISION:
                raise ValidationError('每笔付款最多上传20个凭证。')
            with domain_write():
                voucher = PaymentVoucher.objects.create(tenant=request.user.tenant, created_by=request.user,
                    payment=record, file_name=name, media_type=media_type, byte_size=len(body), sha256=digest,
                    idempotency_key=idem_key, content=body)
                services._event(request.user, record, 'payment_voucher_uploaded', idem_key, payload,
                    audit={'payment_voucher_id': voucher.pk})
        return Response({'data': _metadata(voucher)}, status=201)


class PaymentRecordVoucherDownload(InternalAPI):
    http_method_names = ['get', 'options']

    def get(self, request, kind, pk, payment_id, voucher_id):
        PaymentRecordVouchers()._record(request, kind, pk, payment_id, VIEW)
        voucher = PaymentVoucher.objects.filter(tenant_id=request.user.tenant_id, payment_id=payment_id, pk=voucher_id).first()
        if voucher is None:
            raise NotFound('付款凭证不存在或无权访问。')
        if hashlib.sha256(bytes(voucher.content)).hexdigest() != voucher.sha256:
            raise ValidationError('凭证完整性校验失败。')
        response = FileResponse(BytesIO(bytes(voucher.content)), as_attachment=True, filename=voucher.file_name, content_type=voucher.media_type)
        response['Content-Disposition'] = content_disposition_header(True, voucher.file_name)
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-File-SHA256'] = voucher.sha256
        return response

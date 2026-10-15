from io import BytesIO
from django.http import FileResponse
from django.db.models import Q
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from . import notifications as service, notification_config as cfg
from .models import NotificationChannel, SupplierGroupBinding, NotificationOutbox
from .permissions import VIEW, internal_orders
from .serializers import VersionInput
from .views import InternalAPI, _page
from .api import validated, key


class NotifyWriteAPI(InternalAPI):
    write_permission_code = cfg.NOTIFY


class ChannelInput(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    sender_name = serializers.CharField(max_length=120)
    device_name = serializers.CharField(max_length=120)


class ChannelEdit(ChannelInput, VersionInput):
    enabled = serializers.BooleanField(default=False)


class CredentialInput(VersionInput):
    robot_id = serializers.RegexField(r'^[A-Za-z0-9_-]{1,200}$', write_only=True)
    reason = serializers.CharField(max_length=10000)


class QualificationInput(VersionInput):
    first_day = serializers.DateField()
    second_day = serializers.DateField()
    first_day_count = serializers.IntegerField(min_value=6, max_value=100000)
    second_day_count = serializers.IntegerField(min_value=6, max_value=100000)
    evidence = serializers.CharField(max_length=10000)
    contains_external_member = serializers.BooleanField()
    documents_opened = serializers.BooleanField()
    supplier_saved = serializers.BooleanField()
    automatic_without_confirmation = serializers.BooleanField()


class BindingInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=0)
    channel_id = serializers.IntegerField(min_value=1)
    group_name = serializers.CharField(max_length=160)
    target_title = serializers.CharField(max_length=60)
    member_count = serializers.IntegerField(min_value=2, allow_null=True, default=None)
    group_note = serializers.CharField(max_length=10000, allow_blank=True, default='')
    contains_external_member = serializers.BooleanField(default=False)
    sender_member_confirmed = serializers.BooleanField(default=False)
    unique_target_confirmed = serializers.BooleanField(default=False)
    evidence = serializers.CharField(max_length=10000, allow_blank=True, default='')
    enabled = serializers.BooleanField(default=False)


class ReasonInput(VersionInput):
    reason = serializers.CharField(max_length=10000)


class EvidenceInput(VersionInput):
    result = serializers.ChoiceField(choices=['delivered', 'not_delivered'])
    evidence = serializers.CharField(max_length=10000)
    execution_stopped = serializers.BooleanField(default=False)


class Channels(NotifyWriteAPI):
    def get(self, request):
        if not request.user.is_active:
            raise PermissionDenied('采购账号已停用。')
        cfg.require_internal_supply_permission(request.user, VIEW)
        return _page(request, NotificationChannel.objects.filter(tenant=request.user.tenant), cfg.channel_data)

    def post(self, request):
        return Response({'data': cfg.channel_data(cfg.save_channel(request.user, None, validated(ChannelInput, request), key(request)))}, status=201)


class ChannelDetail(NotifyWriteAPI):
    def put(self, request, pk):
        return Response({'data': cfg.channel_data(cfg.save_channel(request.user, pk, validated(ChannelEdit, request), key(request)))})


class ChannelCredentials(NotifyWriteAPI):
    def post(self, request, pk):
        return Response({'data': cfg.channel_data(cfg.credentials(request.user, pk, validated(CredentialInput, request), key(request)))})


class ChannelQualification(NotifyWriteAPI):
    def post(self, request, pk):
        return Response({'data': cfg.channel_data(cfg.qualify_channel(request.user, pk, validated(QualificationInput, request), key(request)))})


class ChannelCheck(NotifyWriteAPI):
    def post(self, request, pk):
        return Response({'data': cfg.channel_data(service.check_channel(request.user, pk, validated(VersionInput, request), key(request)))})


class CallbackLink(InternalAPI):
    read_permission_code = cfg.NOTIFY

    def get(self, request, pk):
        cfg.require_notify(request.user)
        return Response({'data': {'url': cfg.callback_link(cfg.channel_for(request.user, pk, cfg.NOTIFY))}})


class SupplierBinding(NotifyWriteAPI):
    def get(self, request, supplier_id):
        supplier = cfg.supplier_for(request.user, supplier_id)
        obj = SupplierGroupBinding.objects.filter(tenant=request.user.tenant, supplier=supplier).select_related('channel').first()
        return Response({'data': cfg.binding_data(obj)})

    def put(self, request, supplier_id):
        return Response({'data': cfg.binding_data(cfg.save_binding(request.user, supplier_id, validated(BindingInput, request), key(request)))})


class Notifications(InternalAPI):
    def get(self, request):
        rows = service.rows_for(request.user)
        if request.query_params.get('order_id'):
            try:
                rows = rows.filter(order_id=int(request.query_params['order_id']))
            except (ValueError, TypeError):
                raise serializers.ValidationError('采购单标识无效。')
        if request.query_params.get('status'):
            rows = rows.filter(status=request.query_params['status'])
        search = request.query_params.get('search', '').strip()
        if search:
            rows = rows.filter(Q(order__number__icontains=search) | Q(order__supplier__name__icontains=search))
        return _page(request, rows, lambda obj: service.data(obj, detail=False))


class NotificationDetail(InternalAPI):
    def get(self, request, pk):
        return Response({'data': service.data(service.outbox_for(request.user, pk))})


class OrderNotification(InternalAPI):
    def get(self, request, pk):
        from .models import PurchaseOrder
        if not internal_orders(request.user, PurchaseOrder.objects.all()).filter(pk=pk).exists():
            raise NotFound('采购单不可访问。')
        obj = service.rows_for(request.user).filter(order_id=pk).order_by('-id').first()
        return Response({'data': service.data(obj) if obj else None})


class PrepareNotification(InternalAPI):
    def post(self, request, pk):
        return Response({'data': service.data(service.prepare(request.user, pk, validated(VersionInput, request), key(request)))})


class RetargetNotification(NotifyWriteAPI):
    def post(self, request, pk):
        return Response({'data': service.data(service.retarget(request.user, pk, validated(ReasonInput, request), key(request)))})


class ReconcileNotification(NotifyWriteAPI):
    def post(self, request, pk):
        return Response({'data': service.data(service.reconcile(request.user, pk, validated(VersionInput, request), key(request)))})


class RetryPart(NotifyWriteAPI):
    def post(self, request, pk, part_id):
        return Response({'data': service.data(service.retry(request.user, pk, part_id, validated(ReasonInput, request), key(request)))})


class VerifyPart(NotifyWriteAPI):
    def post(self, request, pk, part_id):
        return Response({'data': service.data(service.verify(request.user, pk, part_id, validated(EvidenceInput, request), key(request)))})


def file_response(part, body):
    response = FileResponse(BytesIO(body), as_attachment=True, filename=part.object_name, content_type=part.content_type)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


class PreviewDownload(InternalAPI):
    def get(self, request, pk, part_id):
        obj = service.outbox_for(request.user, pk)
        part = service.part_for(obj, part_id)
        if part.kind not in ('excel','pdf'):
            raise NotFound('该通知部件没有附件。')
        import hashlib
        body = bytes(part.body)
        if hashlib.sha256(body).hexdigest() != part.sha256:
            raise NotFound('文件校验失败。')
        return file_response(part, body)


class WorkToolCallback(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    http_method_names = ['post', 'options']

    def post(self, request, channel_id):
        if len(request.body) > 128 * 1024:
            raise serializers.ValidationError('执行回调过大。')
        channel = NotificationChannel.objects.filter(pk=channel_id).first()
        if not channel:
            raise PermissionDenied('执行回调凭据无效。')
        cfg.check_callback(channel, request.query_params.get('signature', ''))
        if not isinstance(request.data, dict):
            raise serializers.ValidationError('执行回调无效。')
        service.record_result(channel, request.data)
        return Response({'success': True})


class PublicDownload(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    http_method_names = ['get', 'options']

    def get(self, request, attempt_id, token):
        if len(token) > 100:
            raise NotFound('文件下载授权已失效。')
        part, body = service.download_material(attempt_id, token)
        return file_response(part, body)

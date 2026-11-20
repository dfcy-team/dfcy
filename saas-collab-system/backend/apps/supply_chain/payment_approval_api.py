from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.tenants.models import Tenant
from apps.purchasing.supply_permissions import require_internal_supply_permission
from . import services
from .models import BusinessEvent, domain_write
from .numbering_api import _can_manage
from .permissions import VIEW
from .views import InternalAPI


def approval_required(actor):
    return Tenant.objects.values_list('payment_approval_required', flat=True).get(pk=actor.tenant_id)


class ModeInput(serializers.Serializer):
    approval_required = serializers.BooleanField()
    expected_version = serializers.IntegerField(min_value=0)
    reason = serializers.CharField(max_length=300)


class PaymentApprovalMode(InternalAPI):
    def get(self, request):
        require_internal_supply_permission(request.user, VIEW)
        return self.response(request.user, request.user.tenant)

    @transaction.atomic
    def patch(self, request):
        actor = request.user
        if not _can_manage(actor):
            raise PermissionDenied()
        data = ModeInput(data=request.data)
        data.is_valid(raise_exception=True)
        payload = data.validated_data
        tenant = Tenant.objects.select_for_update().get(pk=actor.tenant_id)
        if tenant.payment_approval_version != payload['expected_version']:
            raise ValidationError('设置已变化，请重新打开设置。')
        previous = tenant.payment_approval_required
        tenant.payment_approval_required = payload['approval_required']
        tenant.payment_approval_version += 1
        tenant.save(update_fields=['payment_approval_required', 'payment_approval_version', 'updated_at'])
        with domain_write():
            BusinessEvent.objects.create(
                tenant=tenant, created_by=actor, aggregate_type='tenant_payment_approval',
                aggregate_id=tenant.pk, aggregate_version=tenant.payment_approval_version,
                action='settings_updated', request_key=f'payment-approval-{tenant.payment_approval_version}',
                request_hash=services.request_hash(payload), payload={**payload, 'previous': previous},
            )
        return self.response(actor, tenant)

    @staticmethod
    def response(actor, tenant):
        return Response({'data': {'approval_required': tenant.payment_approval_required,
                                  'version': tenant.payment_approval_version,
                                  'can_manage': _can_manage(actor)}})

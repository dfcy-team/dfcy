"""Prepare or enable exact business-flow mappings; dry-run by default."""
import json
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.accounts.models import CustomUser
from apps.workflows.models import PaymentApprovalFlow
from apps.integrations.models import FeishuApprovalMapping
from apps.integrations.feishu_native_client import FeishuNativeClient
from apps.integrations.feishu_native_approval import _connection, _identity, definition_hash
from apps.integrations.feishu_payment_preflight import inspect_definition


class Command(BaseCommand):
    help = 'Prepare native payment mappings after template and callback checks. Dry-run unless --apply.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', type=int, required=True)
        parser.add_argument('--flow-key', required=True)
        parser.add_argument('--reviewer-id', type=int, required=True)
        parser.add_argument('--approval-code', required=True)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--subscribe', action='store_true')
        parser.add_argument('--enable', action='store_true')
        parser.add_argument('--fixed-assignees-verified', action='store_true')

    def handle(self, *args, **options):
        tenant_id = options['tenant_id']
        flows = list(PaymentApprovalFlow.objects.filter(tenant_id=tenant_id, flow_key=options['flow_key'], active=True, published=True))
        reviewer = CustomUser.objects.filter(pk=options['reviewer_id'], tenant_id=tenant_id, is_active=True, user_type='internal').first()
        if not flows or not reviewer or any(flow.reviewer_id != reviewer.pk for flow in flows):
            raise CommandError('Published system flow and reviewer do not match.')
        connection = _connection(tenant_id)
        reviewer_open_id = _identity(reviewer)
        client = FeishuNativeClient()
        definition = client.get_definition(connection, options['approval_code'])
        report = inspect_definition(definition, ['CNY', 'PHP'])
        if report['issues']:
            raise CommandError('Template preflight failed: '+','.join(report['issues']))
        fingerprint = definition_hash(definition)
        if options['enable'] and not (options['apply'] and options['subscribe'] and options['fixed_assignees_verified']):
            raise CommandError('Enabling requires --apply --subscribe --fixed-assignees-verified.')
        if not options['apply']:
            self.stdout.write(json.dumps({'status':'READY_FOR_REVIEW','write':False,'tenant_id':tenant_id,
                'flow_ids':[f.pk for f in flows],'reviewer_id':reviewer.pk,'definition_hash':fingerprint,
                'business_types':['supply_payment_request','supply_payment_batch'],
                'fixed_assignees_verified':False,'subscription_verified':False}))
            return
        if options['subscribe']:
            client.subscribe(connection, options['approval_code'])
        with transaction.atomic():
            for business_type in ['supply_payment_request','supply_payment_batch']:
                FeishuApprovalMapping.objects.update_or_create(tenant_id=tenant_id, flow_key=options['flow_key'], business_type=business_type,
                    defaults={'approval_code':options['approval_code'],'definition':definition,'definition_hash':fingerprint,
                        'reviewer_id':reviewer.pk,'reviewer_open_id':reviewer_open_id,
                        'fixed_assignees_verified':options['fixed_assignees_verified'],
                        'subscription_verified':options['subscribe'],'enabled':options['enable']})
        self.stdout.write(json.dumps({'status':'ENABLED' if options['enable'] else 'PREPARED','tenant_id':tenant_id,
            'definition_hash':fingerprint,'subscription_verified':options['subscribe'],'business_type_count':2}))

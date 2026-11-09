from datetime import timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import TestCase
from django.utils import timezone
from apps.tenants.models import Tenant
from apps.integrations.models import DeveloperApplication
from apps.integrations.developer_apps import authenticate_developer_token

class DeveloperTokenTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(code="DEVAPP1",name="Developer tenant")
        self.owner=get_user_model().objects.create_user(username="developer-owner",tenant=self.tenant,user_type="internal",is_active=True)
        self.app=DeveloperApplication.objects.create(tenant=self.tenant,owner=self.owner,updated_by=self.owner,name="App",expires_at=timezone.now()+timedelta(days=2),status="active",approval_status="pending",secret_hash=make_password("one-time-secret"))
        self.app.approved_endpoint_ids=[7]
        self.app.save()

    def test_pending_expansion_keeps_existing_active_grant_token_valid(self):
        self.app.approved_endpoint_ids=[7]
        self.app.requested_endpoint_ids=[7,9]
        self.app.save()
        self.assertEqual(authenticate_developer_token(f"{self.app.pk}.one-time-secret").pk,self.app.pk)
        self.assertEqual(self.app.approved_endpoint_ids,[7])

    def test_revoked_or_expired_app_token_fails_closed(self):
        self.app.secret_hash=""
        self.app.save()
        self.assertIsNone(authenticate_developer_token(f"{self.app.pk}.one-time-secret"))
        self.app.secret_hash=make_password("one-time-secret")
        self.app.expires_at=timezone.now()-timedelta(seconds=1)
        self.app.save()
        self.assertIsNone(authenticate_developer_token(f"{self.app.pk}.one-time-secret"))

    def test_token_is_app_id_addressed_and_secret_is_checked(self):
        self.assertIsNone(authenticate_developer_token(f"{self.app.pk}.wrong-secret"))
        self.assertIsNone(authenticate_developer_token("not-a-token"))

    def test_token_fails_if_owner_moves_tenants_or_becomes_external(self):
        token=f"{self.app.pk}.one-time-secret"
        other_tenant=Tenant.objects.create(code="DEVAPP2",name="Other developer tenant")
        self.owner.tenant=other_tenant
        self.owner.save(update_fields=["tenant"])
        self.assertIsNone(authenticate_developer_token(token))
        self.owner.tenant=self.tenant
        self.owner.user_type="external"
        self.owner.save(update_fields=["tenant","user_type"])
        self.assertIsNone(authenticate_developer_token(token))


from rest_framework.test import APITestCase
from apps.permissions.models import Permission, Role, UserRole
from apps.integrations.models import DeveloperEndpoint, PlatformIntegrationConfig
import io, zipfile


class DeveloperApplicationAPITests(APITestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(code='DAP',name='Development')
        users=get_user_model()
        self.owner=users.objects.create_user(username='dev-user',tenant=self.tenant,user_type='internal',is_active=True)
        self.admin=users.objects.create_user(username='dev-reviewer',tenant=self.tenant,user_type='internal',is_active=True,is_superuser=True)
        role=Role.objects.create(tenant=self.tenant,code='developer',name='Developer')
        for action in ['view','manage']:
            perm,_=Permission.objects.get_or_create(code=f'integrations.developer_app.{action}',defaults={'name':action,'module':'integrations','action':f'developer_app.{action}'})
            role.permissions.add(perm)
        UserRole.objects.create(tenant=self.tenant,user=self.owner,role=role)
        config=PlatformIntegrationConfig.objects.create(tenant=self.tenant,platform='shopee',account_alias='test',environment='sandbox',created_by=self.admin)
        self.endpoint=DeveloperEndpoint.objects.create(config=config,code='orders',name='Orders',method='GET',relative_path='/orders',base_url='https://api.example.com',auth_mode='bearer',approved=True,created_by=self.admin)
        self.extra=DeveloperEndpoint.objects.create(config=config,code='stocks',name='Stocks',method='GET',relative_path='/stocks',base_url='https://api.example.com',auth_mode='bearer',approved=True,created_by=self.admin)
        self.root='/api/internal/integrations/developer-apps/'
        self.client.force_authenticate(self.owner)

    def create_app(self):
        response=self.client.post(self.root,{'name':'Local app','endpoint_ids':[self.endpoint.id]},format='json')
        self.assertEqual(response.status_code,201,response.content)
        return response.json()['data']['id']

    def test_menu_only_grant_can_read_but_cannot_mutate(self):
        pk = self.create_app()
        role = Role.objects.get(tenant=self.tenant, code='developer')
        role.permissions.clear()
        menu, _ = Permission.objects.update_or_create(
            code='menu.integrations.developer_apps.view',
            defaults={'name': 'Developer menu', 'module': 'integrations',
                      'action': 'view', 'permission_type': Permission.PermissionType.MENU,
                      'metadata': {'action_codes': ['integrations.developer_app.view']}},
        )
        role.permissions.add(menu)
        for path in [self.root, '/api/internal/integrations/developer-catalog/',
                     f'{self.root}{pk}/', f'{self.root}{pk}/logs/', f'{self.root}{pk}/docs/']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        for path in [self.root, f'{self.root}{pk}/token/', f'{self.root}{pk}/revoke/',
                     '/api/internal/integrations/developer-catalog/']:
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, {}, format='json').status_code, 403)
        self.assertEqual(self.client.patch(f'{self.root}{pk}/', {'name': 'Denied'}, format='json').status_code, 403)

    def test_no_developer_grant_cannot_read(self):
        Role.objects.get(tenant=self.tenant, code='developer').permissions.clear()
        self.assertEqual(self.client.get(self.root).status_code, 403)
        self.assertEqual(self.client.get('/api/internal/integrations/developer-catalog/').status_code, 403)

    def approve(self, pk):
        self.client.force_authenticate(self.admin)
        response=self.client.post(f'{self.root}{pk}/review/',{'decision':'approve'},format='json')
        self.assertEqual(response.status_code,200,response.content)
        self.client.force_authenticate(self.owner)

    def test_developer_create_approve_token_expand_revoke(self):
        pk=self.create_app()
        self.assertEqual(self.client.post(f'{self.root}{pk}/token/').status_code,400)
        self.approve(pk)
        token=self.client.post(f'{self.root}{pk}/token/').json()['data']['token']
        app=DeveloperApplication.objects.get(pk=pk); old_expiry=app.expires_at
        self.assertIsNotNone(authenticate_developer_token(token))
        response=self.client.patch(f'{self.root}{pk}/',{'endpoint_ids':[self.endpoint.id,self.extra.id], 'expires_at':(timezone.now()+timedelta(days=20)).isoformat()},format='json')
        self.assertEqual(response.status_code,200,response.content)
        app.refresh_from_db()
        self.assertEqual(app.expires_at,old_expiry)
        self.assertEqual(app.approved_endpoint_ids,[self.endpoint.id])
        self.assertIsNotNone(authenticate_developer_token(token))
        self.approve(pk)
        app.refresh_from_db(); self.assertIn(self.extra.id,app.approved_endpoint_ids)
        self.assertIsNotNone(authenticate_developer_token(token))
        docs=self.client.get(f'{self.root}{pk}/docs/')
        self.assertEqual(docs.status_code,200)
        with zipfile.ZipFile(io.BytesIO(docs.content)) as archive:
            self.assertIn('postman.json',archive.namelist())
            self.assertNotIn(token,''.join(archive.read(n).decode() for n in archive.namelist()))
        self.assertEqual(self.client.post(f'{self.root}{pk}/revoke/').status_code,200)
        self.assertIsNone(authenticate_developer_token(token))

    def test_owner_and_tenant_isolation_and_registration(self):
        pk=self.create_app()
        self.assertEqual(self.client.post('/api/internal/integrations/developer-catalog/',{},format='json').status_code,403)
        other=get_user_model().objects.create_user(username='another',tenant=self.tenant,user_type='internal',is_active=True,is_superuser=True)
        self.client.force_authenticate(other)
        self.assertEqual(self.client.post(f'{self.root}{pk}/token/').status_code,404)
        rows=self.client.get(self.root).json()['data']['items']; self.assertIn(pk,[a['id'] for a in rows])
        other.tenant=Tenant.objects.create(code='DAP2',name='Other');other.save()
        self.assertEqual(self.client.post(f'{self.root}{pk}/review/',{'decision':'approve'},format='json').status_code,404)

    def test_self_review_denied_and_invalid_expiry_rejected(self):
        self.client.force_authenticate(self.admin)
        pk=self.create_app()
        self.assertEqual(self.client.post(f'{self.root}{pk}/review/',{'decision':'approve'},format='json').status_code,400)
        response=self.client.post(self.root,{'name':'bad','endpoint_ids':[self.endpoint.id],'expires_at':'not-a-date'},format='json')
        self.assertEqual(response.status_code,400)

    def test_admin_can_inspect_and_revoke_but_not_take_owner_token(self):
        pk=self.create_app(); self.approve(pk)
        token=self.client.post(f'{self.root}{pk}/token/').json()['data']['token']
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(f'{self.root}{pk}/').status_code,200)
        self.assertEqual(self.client.get(f'{self.root}{pk}/logs/').status_code,200)
        self.assertEqual(self.client.get(f'{self.root}{pk}/docs/').status_code,200)
        self.assertEqual(self.client.post(f'{self.root}{pk}/token/').status_code,404)
        self.assertEqual(self.client.post(f'{self.root}{pk}/revoke/').status_code,200)
        self.assertIsNone(authenticate_developer_token(token))

    def test_invalid_catalog_origin_is_validation_error(self):
        self.client.force_authenticate(self.admin)
        response=self.client.post('/api/internal/integrations/developer-catalog/',{
            'connection_id':self.endpoint.config_id,'code':'bad','name':'Bad URL',
            'method':'GET','path':'/orders','auth_mode':'bearer','base_url':'https://['
        },format='json')
        self.assertEqual(response.status_code,400)

    def test_shopee_signed_gateway_token_rotation_and_revocation(self):
        import json
        from unittest.mock import patch
        from urllib.parse import urlsplit, parse_qs
        from rest_framework.test import APIClient
        from apps.masterdata.models import PlatformMaster, StoreMaster
        from apps.integrations.models import (MarketplaceStoreAuthorization, authorization_service_write,
            marketplace_identity_key, marketplace_active_identity_key, marketplace_store_binding_key, DeveloperCallLog)
        from apps.integrations.net_guard import HttpResponse
        from apps.integrations.live_providers import _hmac_sha256
        from apps.integrations import developer_transport as transport
        config=self.endpoint.config
        config.status='verified'; config.network_enabled=True; config.sync_read_enabled=True
        config.environment='production'; config.sync_write_enabled=False
        config.credential_id='fake-ref'; config.platform_config={'partner_id':'123'}
        with authorization_service_write(): config.save()
        platform=PlatformMaster.objects.create(tenant=self.tenant,code='SP',name='Shopee',platform_type='shopee')
        store=StoreMaster.objects.create(tenant=self.tenant,platform=platform,code='SP1',name='Synthetic shop',country_code='PH')
        with authorization_service_write():
            account=MarketplaceStoreAuthorization.objects.create(tenant=self.tenant,integration_config=config,
                store=store,platform='shopee',region='PH',platform_store_id='456',status='active',
                platform_identity_key=marketplace_identity_key('shopee','PH','456'),
                active_platform_identity_key=marketplace_active_identity_key('shopee','PH','456'),
                active_store_binding_key=marketplace_store_binding_key(self.tenant.pk,'shopee',store.pk),
                merchant_subject_id='fake-merchant',credential_id='fake-ref',token_id='fake-token-ref',
                created_by=self.admin,updated_by=self.admin)
        self.endpoint.account=account; self.endpoint.auth_mode='shopee_shop'
        self.endpoint.relative_path='/api/v2/order/get_order_list'; self.endpoint.save()
        self.client.force_authenticate(self.admin)
        payload={'connection_id':config.pk,'account_id':account.pk,'code':'platform-root','name':'Root','method':'GET','path':'/','auth_mode':'shopee_shop','base_url':'https://api.example.com'}
        with patch('apps.integrations.production_settings.get_runtime_platform_config',return_value={'api_host':'https://api.example.com'}), patch('apps.integrations.developer_transport.assert_host_allowed'):
            for override in [{'account_id':None},{'auth_mode':'bearer'},{'base_url':'https://other.example.com'}]:
                self.assertEqual(self.client.post('/api/internal/integrations/developer-catalog/',{**payload,**override},format='json').status_code,400)
            response=self.client.post('/api/internal/integrations/developer-catalog/',payload,format='json')
            self.assertEqual(response.status_code,201,response.content)
            self.assertEqual(response.json()['data']['scope_mode'],'platform')
            self.assertEqual(self.client.post('/api/internal/integrations/developer-catalog/',payload,format='json').status_code,400)
        self.endpoint.refresh_from_db()
        self.assertEqual(self.endpoint.scope_mode,'fixed')
        self.client.force_authenticate(self.owner)
        pk=self.create_app(); self.approve(pk)
        token=self.client.post(f'{self.root}{pk}/token/').json()['data']['token']
        external=APIClient(); url=f'/api/developer-gateway/v1/{pk}/orders/'
        def wire(method,url,**kwargs):
            parsed=urlsplit(url); query={k:v[0] for k,v in parse_qs(parsed.query).items()}
            self.assertEqual(method,'GET'); self.assertEqual(query['shop_id'],'456')
            self.assertEqual(query['sign'],_hmac_sha256('fake-secret',f"123{parsed.path}{query['timestamp']}fake-access456"))
            return HttpResponse(200,{},json.dumps({'error':'','response':{'order_list':[{'order_sn':'fake-order'}],'more':False}}))
        with patch('apps.integrations.developer_gateway._consume_rate_limit', return_value=True), patch.object(transport,'get_custody_backend') as custody, patch.object(transport,'assert_host_allowed'), patch('apps.integrations.net_guard.assert_host_allowed'), patch.object(transport,'gateway_transport',side_effect=wire) as outbound, patch('apps.integrations.production_settings.get_runtime_platform_config',return_value={'api_host':'https://api.example.com'}):
            custody.return_value.retrieve_access_token.return_value='fake-access'
            custody.return_value.retrieve_secret.return_value='fake-secret'
            response=external.post(url,{'query':{'page_size':1}},format='json',HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code,200,response.content)
            self.assertEqual(response.json()['data']['response']['order_list'][0]['order_sn'],'fake-order')
            self.assertEqual(external.post(f'/api/developer-gateway/v1/{pk}/stocks/',{},format='json',HTTP_AUTHORIZATION=f'Bearer {token}').status_code,403)
            self.assertEqual(outbound.call_count,1)
            replacement=self.client.post(f'{self.root}{pk}/token/').json()['data']['token']
            self.assertEqual(external.post(url,{},format='json',HTTP_AUTHORIZATION=f'Bearer {token}').status_code,401)
            self.assertEqual(external.post(url,{},format='json',HTTP_AUTHORIZATION=f'Bearer {replacement}').status_code,200)
            self.client.post(f'{self.root}{pk}/revoke/')
            self.assertEqual(external.post(url,{},format='json',HTTP_AUTHORIZATION=f'Bearer {replacement}').status_code,401)
            self.assertEqual(outbound.call_count,2)
        logs=str(list(DeveloperCallLog.objects.filter(application_id=pk).values_list('detail',flat=True)))
        for secret in [token,replacement,'fake-access','fake-secret','fake-order']:
            self.assertNotIn(secret,logs)

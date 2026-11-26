"""Disposable local acceptance server; isolated SQLite, no business database."""
import os, sys, json, secrets
from pathlib import Path
root=Path(__file__).resolve().parents[1]
state=root/'.codex-work'/'issue-tracking-local'; state.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(root/'saas-collab-system'/'backend'))
os.environ['DJANGO_SETTINGS_MODULE']='config.settings.dev'
from django.conf import settings
settings.DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':str(state/'acceptance.sqlite3')}}
keyfile=state/'secret-key.txt'
if not keyfile.exists(): keyfile.write_text(secrets.token_urlsafe(48),encoding='utf-8')
settings.SECRET_KEY=keyfile.read_text(encoding='utf-8')
settings.ALLOWED_HOSTS=['127.0.0.1','localhost','testserver']
settings.CORS_ALLOWED_ORIGINS=['http://127.0.0.1:5178']
settings.LIVE_READONLY_SYNC_ENABLED=False
settings.PLATFORM_NETWORK_MODE='disabled'
import django; django.setup()
from django.apps import apps
settings.MIGRATION_MODULES={app.label:None for app in apps.get_app_configs()}
from django.core.management import call_command
if '--init' in sys.argv:
    call_command('migrate',run_syncdb=True,interactive=False,verbosity=0)
    from apps.tenants.models import Tenant,Department
    from apps.accounts.models import CustomUser,InternalUserProfile
    from apps.issue_tracking.models import MenuRule
    tenant,_=Tenant.objects.get_or_create(code='tracking-local-acceptance',defaults={'name':'事项跟踪本地验收'})
    dept,_=Department.objects.get_or_create(tenant=tenant,name='本地验收部门')
    password=secrets.token_urlsafe(24)
    for name,admin in [('tracking-local-admin',True),('tracking-local-handler',False)]:
        user,_=CustomUser.objects.get_or_create(username=name,defaults={'tenant':tenant,'user_type':'internal'})
        user.is_superuser=admin;user.is_staff=admin;user.set_password(password);user.save()
        InternalUserProfile.objects.get_or_create(user=user,defaults={'tenant':tenant,'department':dept})
    MenuRule.objects.get_or_create(tenant=tenant,menu_key='/workflow/approvals',defaults={'enabled':True})
    (state/'credentials.json').write_text(json.dumps({'username':'tracking-local-admin','password':password}),encoding='utf-8')
    print('Isolated acceptance database initialized; credentials saved locally.')
if '--serve' in sys.argv: call_command('runserver','127.0.0.1:8018',use_reloader=False)

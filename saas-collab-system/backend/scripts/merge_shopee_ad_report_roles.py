"""Run via manage.py shell: exec(open(path).read()); defaults to preview.
Set MERGE_MODE=apply/restore, MERGE_BACKUP and MERGE_ACTOR_ID explicitly.
"""
import json
import os
import uuid
from pathlib import Path
from django.contrib.auth import get_user_model
from django.db import transaction
from apps.permissions.models import DataScope, Role, RoleResourcePolicy, UserRole, PermissionChange
from apps.permissions.resource_policies import active_bindings
from apps.reports.advertising_dataset import advertising_store_scope


def run(mode='preview', tenant_id=1, actor_id=None, backup_path=None):
    if mode not in {'preview', 'apply', 'restore'}:
        raise ValueError('Invalid mode')
    if mode != 'preview' and (not backup_path or not actor_id):
        raise ValueError('Mutation requires actor and backup path')
    with transaction.atomic():
        actor = None
        if actor_id:
            actor = get_user_model().objects.get(pk=actor_id, tenant_id=tenant_id, is_active=True)
            from apps.permissions.services import check_user_permission
            if not actor.is_superuser:
                raise ValueError('Migration requires tenant superuser actor')
        if mode == 'restore':
            saved = json.loads(Path(backup_path).read_text(encoding='utf-8'))
            if saved['tenant_id'] != tenant_id:
                raise ValueError('Backup tenant mismatch')
            changes = []
            for row in saved['bindings']:
                binding = UserRole.objects.select_for_update().get(pk=row['id'], tenant_id=tenant_id,
                    user_id=row['user_id'], role_id=row['role_id'])
                if binding.status != 'inactive':
                    raise ValueError('Binding changed since migration')
                binding.status = row['status']
                binding.save(update_fields=['status'])
                changes.append({'id': binding.pk, 'status': binding.status})
            PermissionChange.objects.create(tenant_id=tenant_id, actor=actor, batch_id=uuid.uuid4(),
                reason='Restore advertising personal role bindings', operation='ad_roles_restore', changes=changes)
            return {'status': 'restored', 'bindings': changes}
        target = Role.objects.select_for_update().get(tenant_id=tenant_id, code='operations-Shopee', status='active')
        if not {'reports.view', 'analytics.view'} <= set(target.permissions.values_list('code', flat=True)):
            raise ValueError('Target lacks required permissions')
        users, bindings = [], []
        for username in ('lanx', 'zhanzq'):
            user = get_user_model().objects.select_for_update().get(tenant_id=tenant_id, username=username, is_active=True)
            if not active_bindings(user).filter(role=target).exists():
                raise ValueError('Missing effective target role: ' + username)
            role = Role.objects.select_for_update().get(tenant_id=tenant_id, code='feishu-ads-report-' + username)
            if UserRole.objects.filter(role=role, status='active').exclude(user=user).exists():
                raise ValueError('Unexpected personal role member')
            selected = list(UserRole.objects.select_for_update().filter(tenant_id=tenant_id, user=user, role=role, status='active'))
            if not selected:
                raise ValueError('No active personal binding: ' + username)
            before = advertising_store_scope(user)
            ids = [b.pk for b in selected]
            other_bindings = active_bindings(user).exclude(pk__in=ids).select_related('role')
            remaining_roles = [binding.role for binding in other_bindings]
            removed_permissions = set(role.permissions.values_list('code', flat=True))
            covered_permissions = set()
            for remaining_role in remaining_roles:
                covered_permissions.update(remaining_role.permissions.values_list('code', flat=True))
            uncovered_permissions = sorted(removed_permissions - covered_permissions)

            # Scope semantics vary by resource. Only treat an identical scope
            # on a remaining role as proven coverage; otherwise surface it for
            # review and block apply rather than widening another role.
            remaining_role_ids = [remaining_role.pk for remaining_role in remaining_roles]
            source_data_scopes = list(DataScope.objects.filter(tenant_id=tenant_id, role=role)
                .values_list('scope_type', 'config'))
            covered_data_scopes = {
                (scope_type, json.dumps(config, sort_keys=True))
                for scope_type, config in DataScope.objects.filter(tenant_id=tenant_id, role_id__in=remaining_role_ids)
                    .values_list('scope_type', 'config')
            }
            uncovered_data_scopes = [
                {'scope_type': scope_type, 'config': config}
                for scope_type, config in source_data_scopes
                if (scope_type, json.dumps(config, sort_keys=True)) not in covered_data_scopes
            ]
            source_resource_policies = list(RoleResourcePolicy.objects.filter(tenant_id=tenant_id, role=role)
                .values('resource_code', 'permission_code', 'scope_type', 'config'))
            covered_resource_policies = {
                (resource, permission, scope_type, json.dumps(config, sort_keys=True))
                for resource, permission, scope_type, config in RoleResourcePolicy.objects.filter(
                    tenant_id=tenant_id, role_id__in=remaining_role_ids
                ).values_list('resource_code', 'permission_code', 'scope_type', 'config')
            }
            uncovered_resource_policies = [
                policy for policy in source_resource_policies
                if (policy['resource_code'], policy['permission_code'], policy['scope_type'],
                    json.dumps(policy['config'], sort_keys=True))
                not in covered_resource_policies
            ]
            source_data_scope_signatures = {
                (scope_type, json.dumps(config, sort_keys=True))
                for scope_type, config in source_data_scopes
            }
            source_resource_policy_signatures = {
                (policy['resource_code'], policy['permission_code'], policy['scope_type'],
                 json.dumps(policy['config'], sort_keys=True))
                for policy in source_resource_policies
            }
            proven_by = []
            for remaining_role in remaining_roles:
                role_permissions = set(remaining_role.permissions.values_list('code', flat=True))
                role_data_scopes = {
                    (scope_type, json.dumps(config, sort_keys=True))
                    for scope_type, config in DataScope.objects.filter(
                        tenant_id=tenant_id, role=remaining_role
                    ).values_list('scope_type', 'config')
                }
                role_resource_policies = {
                    (resource, permission, scope_type, json.dumps(config, sort_keys=True))
                    for resource, permission, scope_type, config in RoleResourcePolicy.objects.filter(
                        tenant_id=tenant_id, role=remaining_role
                    ).values_list('resource_code', 'permission_code', 'scope_type', 'config')
                }
                if (removed_permissions <= role_permissions
                        and source_data_scope_signatures == role_data_scopes
                        and source_resource_policy_signatures == role_resource_policies):
                    proven_by.append(remaining_role.pk)
            authorization_diff = {
                'permissions': uncovered_permissions,
                'data_scopes': uncovered_data_scopes,
                'resource_policies': uncovered_resource_policies,
                'coverage_proof': {
                    'proven': bool(proven_by),
                    'covering_role_ids': proven_by,
                },
            }
            checkpoint = transaction.savepoint()
            UserRole.objects.filter(pk__in=ids).update(status='inactive')
            after = advertising_store_scope(user)
            transaction.savepoint_rollback(checkpoint)
            if before != after:
                raise ValueError('Role removal changes store scope: ' + username)
            users.append({'username': username, 'mode': before[0], 'store_ids': before[1],
                'authorization_diff': authorization_diff})
            bindings.extend({'id': b.pk, 'user_id': b.user_id, 'role_id': b.role_id, 'status': b.status} for b in selected)
        plan = {'tenant_id': tenant_id, 'users': users, 'bindings': bindings, 'target_role_id': target.pk}
        if mode == 'apply':
            if any(any(user['authorization_diff'][key] for key in ('permissions', 'data_scopes', 'resource_policies'))
                   or not user['authorization_diff']['coverage_proof']['proven'] for user in users):
                raise ValueError('Role removal would lose uncovered permissions or resource scopes; review preview')
            with Path(backup_path).open('x', encoding='utf-8') as stream:
                json.dump(plan, stream, ensure_ascii=False, indent=2)
            UserRole.objects.filter(pk__in=[r['id'] for r in bindings]).update(status='inactive')
            PermissionChange.objects.create(tenant_id=tenant_id, actor=actor, batch_id=uuid.uuid4(),
                reason='Consolidate personal advertising roles into existing Shopee operations role',
                operation='ad_roles_merge', changes=bindings)
        return {'status': mode, **plan}


if __name__ == '__main__':
    print(json.dumps(run(os.getenv('MERGE_MODE', 'preview'), int(os.getenv('MERGE_TENANT_ID', '1')),
        int(os.environ['MERGE_ACTOR_ID']) if os.getenv('MERGE_ACTOR_ID') else None,
        os.getenv('MERGE_BACKUP')), ensure_ascii=False))

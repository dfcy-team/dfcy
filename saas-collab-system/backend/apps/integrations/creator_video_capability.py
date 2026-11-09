"""Independent opt-in gate; existing provider/permission checks remain required."""
from rest_framework.exceptions import PermissionDenied
from .models import ConnectionCapability


def require_collection_capability(authorization, code):
    if code not in {'CREATOR', 'VIDEO'} or authorization.platform != 'tiktok':
        raise PermissionDenied('Unsupported collection capability.')
    if not ConnectionCapability.objects.filter(
        authorization_id=authorization.pk,
        authorization__tenant_id=authorization.tenant_id,
        authorization__status='active', capability_code=code,
        read_enabled=True, status='active', write_enabled=False,
    ).exists():
        raise PermissionDenied(f'{code} read capability is disabled; enable it in the store capability matrix.')

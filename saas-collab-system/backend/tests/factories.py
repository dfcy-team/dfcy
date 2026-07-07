from itertools import count

from apps.accounts.models import CustomUser
from apps.rpa.models import RPAAgent
from apps.tenants.models import Tenant


_sequence = count(1)


def create_tenant(name=None, code=None, **kwargs):
    index = next(_sequence)
    return Tenant.objects.create(
        name=name or f"Test Tenant {index}",
        code=code or f"test-tenant-{index}",
        **kwargs,
    )


def create_internal_user(tenant=None, username=None, password="test-password", **kwargs):
    index = next(_sequence)
    tenant = tenant or create_tenant()
    return CustomUser.objects.create_user(
        username=username or f"internal-user-{index}",
        password=password,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        **kwargs,
    )


def create_rpa_agent(tenant=None, name=None, token_hash="test-token-hash", **kwargs):
    index = next(_sequence)
    tenant = tenant or create_tenant()
    return RPAAgent.objects.create(
        tenant=tenant,
        name=name or f"RPA Agent {index}",
        token_hash=token_hash,
        **kwargs,
    )

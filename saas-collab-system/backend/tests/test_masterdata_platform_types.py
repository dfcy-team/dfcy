import pytest

from apps.masterdata.models import PlatformMaster
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def test_lazada_and_temu_have_independent_platform_types():
    choices = dict(PlatformMaster.PlatformType.choices)
    assert choices["lazada"] == "LAZADA"
    assert choices["temu"] == "TEMU"
    assert choices["lazada"] != choices["temu"]

    tenant = Tenant.objects.create(name="Platform types tenant", code="platform-types")
    lazada = PlatformMaster.objects.create(
        tenant=tenant,
        code="lazada",
        name="LAZADA",
        platform_type=PlatformMaster.PlatformType.LAZADA,
    )
    temu = PlatformMaster.objects.create(
        tenant=tenant,
        code="temu",
        name="TEMU",
        platform_type=PlatformMaster.PlatformType.TEMU,
    )

    assert lazada.platform_type == "lazada"
    assert temu.platform_type == "temu"
    assert lazada.platform_type != temu.platform_type

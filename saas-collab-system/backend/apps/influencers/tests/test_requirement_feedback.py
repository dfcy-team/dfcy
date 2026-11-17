import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.influencers.requirement_feedback import InfluencerRequirementView
from apps.influencers.tests.test_import_compatibility import sample_records
from apps.permissions.models import Permission, Role, UserRole

pytestmark = pytest.mark.django_db


def grant(user, suffix):
    code = f"influencers.requirements.{suffix}"
    permission, _ = Permission.objects.get_or_create(code=code)
    role = Role.objects.create(tenant=user.tenant, code=suffix, name=suffix)
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)


def call(user, method="get", payload=None):
    factory = APIRequestFactory()
    request = getattr(factory, method)("/requirements/", payload or {}, format="json")
    force_authenticate(request, user)
    return InfluencerRequirementView.as_view()(request)


def test_requirement_permissions_and_tenant_isolation(sample_records):
    submitter = sample_records["executor"]
    reviewer = sample_records["user"]
    other = sample_records["other_user"]
    assert call(submitter).status_code == 403
    assert call(submitter, "post", {"title": "Example", "description": "Example"}).status_code == 403
    grant(submitter, "submit")
    grant(reviewer, "review")
    grant(other, "review")
    assert call(submitter, "post", {"title": "", "description": "Example"}).status_code == 400
    assert call(submitter, "post", {"title": "Example", "description": "Example", "tenant": other.tenant_id}).status_code == 201
    assert call(reviewer, "post", {"title": "Review example", "description": "Example"}).status_code == 201
    assert call(submitter).data["data"]["count"] == 1
    assert call(reviewer).data["data"]["count"] == 2
    assert call(other).data["data"]["count"] == 0

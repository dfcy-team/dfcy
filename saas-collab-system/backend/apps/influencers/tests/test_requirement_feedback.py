import pytest
from io import BytesIO
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.influencers.requirement_feedback import InfluencerRequirementView, InfluencerRequirementImageView
from apps.influencers.models import InfluencerRequirement, InfluencerRequirementImage
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


def upload(user, files):
    request = APIRequestFactory().post('/requirements/', {"title": "Example", "description": "Example", "images": files}, format="multipart")
    force_authenticate(request, user)
    return InfluencerRequirementView.as_view()(request)


def picture():
    output = BytesIO()
    Image.new("RGB", (20, 20), "white").save(output, "PNG")
    return SimpleUploadedFile("screenshot.png", output.getvalue(), content_type="image/png")


def test_requirement_images_are_private_and_atomic(sample_records):
    author, reviewer, outsider = (sample_records[key] for key in ["executor", "user", "other_user"])
    grant(author, "submit")
    grant(reviewer, "review")
    grant(outsider, "review")
    result = upload(author, [picture()])
    assert result.status_code == 201
    row = InfluencerRequirement.objects.get(pk=result.data["data"]["id"])
    image = row.images.get()
    assert bytes(image.content).startswith(b'\xff\xd8')
    assert call(author).data["data"]["results"][0]["image_ids"] == [image.id]
    for actor, expected in [(author, 200), (reviewer, 200), (outsider, 404)]:
        request = APIRequestFactory().get('/images/')
        force_authenticate(request, actor)
        response = InfluencerRequirementImageView.as_view()(request, pk=row.pk, image_id=image.pk)
        assert response.status_code == expected
        if expected == 200:
            assert response["Cache-Control"] == "private, no-store"
    # A submit-only account cannot read another author's image in the same tenant.
    other_row = InfluencerRequirement.objects.create(tenant=reviewer.tenant, author=reviewer, title="Other", description="Other")
    other_image = InfluencerRequirementImage.objects.create(requirement=other_row, content=image.content)
    request = APIRequestFactory().get('/images/')
    force_authenticate(request, author)
    assert InfluencerRequirementImageView.as_view()(request, pk=other_row.pk, image_id=other_image.pk).status_code == 404


@pytest.mark.parametrize('kind', ['corrupt', 'too_many', 'too_large'])
def test_invalid_images_do_not_create_requirements(sample_records, kind):
    author = sample_records['executor']
    grant(author, "submit")
    files = {
        'corrupt': lambda: [SimpleUploadedFile('fake.png', b'not an image', content_type='image/png')],
        'too_many': lambda: [picture() for _ in range(4)],
        'too_large': lambda: [SimpleUploadedFile('large.png', b'x' * (2 * 1024 * 1024 + 1), content_type='image/png')],
    }[kind]()
    assert upload(author, files).status_code == 400
    assert not InfluencerRequirement.objects.exists()
    assert not InfluencerRequirementImage.objects.exists()

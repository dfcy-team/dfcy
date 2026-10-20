"""Optional archive remarks and tenant-scoped substring search, synthetic only."""
import pytest
from django.db.models import QuerySet

from apps.influencers.models import Influencer, InfluencerContact, InfluencerProfile
from tests.test_influencer_platform_accounts import _records, _form_url


pytestmark = pytest.mark.django_db
COLLECTION = "/api/internal/influencers/"


def _note(record, text):
    record.profile.profile_notes = text
    record.profile.save(update_fields=["profile_notes"])


def _search(record, text, *, query_field="search", **filters):
    response = record.client.get(COLLECTION, {query_field: text, **filters})
    assert response.status_code == 200, response.data
    return response.data["data"]


@pytest.mark.parametrize("value", [None, "", "   "])
def test_archive_remark_is_optional_on_create(value):
    record = _records("optional-remark")
    payload = {"platform": "facebook", "nickname_id": "optional.remark", "account_nickname": "Synthetic creator"}
    if value is not None:
        payload["profile"] = {"profile_notes": value}
    response = record.client.post(COLLECTION + "?include_form=true", payload, format="json")
    assert response.status_code == 201, response.data
    assert (response.data["data"]["profile"] or {}).get("profile_notes", "") == ""


def test_remark_edit_reopens_and_can_be_cleared_without_changing_identity():
    record = _records("editable-remark")
    before_handle = record.influencer.handle
    response = record.client.patch(
        _form_url(record), {"profile": {"profile_notes": "  Fragile goods / evening contact  "}},
        format="json", HTTP_IF_MATCH='"' + record.influencer.updated_at.isoformat() + '"',
    )
    assert response.status_code == 200, response.data
    assert response.data["data"]["profile"]["profile_notes"] == "Fragile goods / evening contact"
    reopened = record.client.get(_form_url(record))
    assert reopened.data["data"]["profile"]["profile_notes"] == "Fragile goods / evening contact"
    cleared = record.client.patch(
        _form_url(record), {"profile": {"profile_notes": ""}}, format="json",
        HTTP_IF_MATCH='"' + response.data["data"]["updated_at"] + '"',
    )
    assert cleared.status_code == 200, cleared.data
    record.profile.refresh_from_db()
    record.influencer.refresh_from_db()
    assert record.profile.profile_notes == ""
    assert record.influencer.handle == before_handle


@pytest.mark.parametrize("nickname_purpose", [False, True])
@pytest.mark.parametrize("term", ["gile pack", "FRAGILE", "\u665a\u95f4\u8054\u7cfb"])
@pytest.mark.parametrize("query_field", ["search", "profile_notes"])
def test_remark_search_matches_partial_content_and_stays_in_tenant(nickname_purpose, term, query_field):
    record = _records("remark-local")
    other = _records("remark-other")
    _note(record, "Please use fragile packaging; \u5efa\u8bae\u665a\u95f4\u8054\u7cfb")
    _note(other, "Please use fragile packaging; \u5efa\u8bae\u665a\u95f4\u8054\u7cfb")
    filters = {"include_nickname_id": "true"} if nickname_purpose else {}
    data = _search(record, term, query_field=query_field, **filters)
    assert data["count"] == 1
    assert [row["id"] for row in data["results"]] == [record.influencer.pk]


@pytest.mark.parametrize("query_field", ["search", "profile_notes"])
def test_remark_search_respects_platform_status_and_literal_wildcards(query_field):
    record = _records("remark-filters")
    _note(record, "special_%_label")
    unrelated = Influencer.objects.create(
        tenant=record.tenant, code="remark-unrelated", name="Unrelated", platform="facebook", handle="unrelated.creator",
    )
    InfluencerProfile.objects.create(tenant=record.tenant, influencer=unrelated, profile_notes="specialXYlabel")
    assert _search(record, "_%_", query_field=query_field)["count"] == 1
    assert _search(record, "_%_", query_field=query_field, platform="facebook")["count"] == 0
    assert _search(record, "_%_", query_field=query_field, platform="tiktok", status="active")["count"] == 1
    assert _search(record, "_%_", query_field=query_field, status="inactive")["count"] == 0


@pytest.mark.parametrize("query_field", ["search", "profile_notes"])
def test_cross_tenant_profile_corruption_does_not_make_notes_searchable(query_field):
    record = _records("remark-corrupt")
    other = _records("remark-corrupt-other")
    _note(record, "ForeignProfileNeedle")
    QuerySet.update(InfluencerProfile.objects.filter(pk=record.profile.pk), tenant_id=other.tenant.pk)
    assert _search(record, "ForeignProfileNeedle", query_field=query_field)["count"] == 0


@pytest.mark.parametrize("query_field", ["search", "profile_notes"])
def test_other_notes_and_contacts_are_not_added_to_remark_search(query_field):
    record = _records("remark-private")
    record.influencer.notes = "HiddenParentNeedle"
    record.influencer.save(update_fields=["notes"])
    InfluencerContact.objects.create(
        tenant=record.tenant, influencer=record.influencer, channel="email",
        value="hidden-contact@example.test", label="HiddenContactNeedle", created_by=record.user,
    )
    for term in ("HiddenParentNeedle", "HiddenContactNeedle", "hidden-contact@example.test"):
        assert _search(record, term, query_field=query_field)["count"] == 0


def test_dedicated_remark_filter_combines_with_general_search_and_pagination():
    record = _records("remark-combined")
    _note(record, "Evening contact preferred")
    for code, remark in (("second-creator", "Evening contact"), ("third-creator", "Morning contact")):
        influencer = Influencer.objects.create(
            tenant=record.tenant, code=code, name=code, platform="tiktok", handle=code,
        )
        InfluencerProfile.objects.create(tenant=record.tenant, influencer=influencer, profile_notes=remark)
    filters = {"profile_notes": "  EVENING  ", "page_size": 1, "ordering": "name"}
    page_one = _search(record, "", **filters)
    page_two = _search(record, "", page=2, **filters)
    assert page_one["count"] == page_two["count"] == 2
    assert len(page_one["results"]) == len(page_two["results"]) == 1
    assert page_one["results"][0]["id"] != page_two["results"][0]["id"]
    matched = _search(record, "remark-combined", profile_notes="Evening")
    assert [row["id"] for row in matched["results"]] == [record.influencer.pk]
    assert _search(record, "third-creator", profile_notes="Evening")["count"] == 0
    assert _search(record, "remark-combined", query_field="profile_notes")["count"] == 0
    assert _search(record, "   ", query_field="profile_notes")["count"] == 3

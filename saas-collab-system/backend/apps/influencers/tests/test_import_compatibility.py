from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from apps.audit.models import OperationLog
from apps.accounts.models import CustomUser
from apps.influencers.models import (
    FulfillmentStatusEvent,
    BdSampleAttributionSnapshot,
    Influencer,
    ImportBatch,
    OutreachTarget,
    OutreachTask,
    SampleFulfillment,
    SampleItem,
)
from apps.influencers.serializers import SampleFulfillmentSerializer
from apps.influencers.services import (
    FEISHU_FULL_SAMPLE_STATUS_SOURCE,
    _import_manifest_digest,
    create_outreach_task,
    create_sample_fulfillment,
    import_outreach_target_snapshot,
    import_outreach_task_snapshot,
    import_sample_fulfillment_snapshot,
    soft_delete_import_source,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _user(tenant, username):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role, _ = Role.objects.get_or_create(tenant=tenant, code="bd", defaults={"name": "BD"})
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    return user


@pytest.fixture
def sample_records():
    tenant = Tenant.objects.create(name="sample-compat", code="sample-compat")
    user = _user(tenant, "sample-owner")
    executor = _user(tenant, "sample-executor")
    other_tenant = Tenant.objects.create(name="other-sample-compat", code="other-sample-compat")
    other_user = _user(other_tenant, "other-sample-owner")
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="sample-compat-platform",
        name="TikTok Shop",
        platform_type=PlatformMaster.PlatformType.TIKTOK,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="sample-compat-store",
        name="Sample store",
        country_code="PH",
        currency="PHP",
    )
    second_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="sample-compat-store-2",
        name="Second sample store",
        country_code="PH",
        currency="PHP",
    )
    influencer = Influencer.objects.create(
        tenant=tenant,
        code="sample-compat-influencer",
        name="Sample creator",
        platform="tiktok",
    )
    second_influencer = Influencer.objects.create(
        tenant=tenant,
        code="sample-compat-influencer-2",
        name="Second creator",
        platform="tiktok",
    )
    task = create_outreach_task(
        user=user,
        validated_data={
            "task_name": "Sample compatibility task",
            "store": store,
            "owner": user,
            "influencer": influencer,
            "external_product_id": "PRODUCT-COMPAT-1",
        },
    )
    return {
        "tenant": tenant,
        "user": user,
        "executor": executor,
        "other_user": other_user,
        "store": store,
        "second_store": second_store,
        "influencer": influencer,
        "second_influencer": second_influencer,
        "task": task,
    }


def test_direct_standalone_allows_missing_product_id_and_serializer_uses_model_choice(sample_records):
    records = sample_records
    serializer = SampleFulfillmentSerializer(
        data={
            "influencer": records["influencer"].pk,
            "store": records["store"].pk,
            "link_type": "direct",
            "product_name_snapshot": "Unmatched direct sample",
        }
    )

    assert serializer.is_valid(), serializer.errors
    fulfillment, created = create_sample_fulfillment(
        user=records["user"],
        request_key="direct-standalone-without-product",
        validated_data=serializer.validated_data,
        item_payloads=[],
    )

    assert created is True
    assert fulfillment.link_type == "direct"
    assert fulfillment.external_product_id == ""
    assert fulfillment.outreach_task_id is None


def test_task_snapshot_uses_source_dates_and_does_not_fabricate_completion(sample_records):
    records = sample_records
    dispatch_time = datetime(2026, 2, 1, 8, 0, tzinfo=dt_timezone.utc)
    start_time = datetime(2026, 2, 2, 9, 30, tzinfo=dt_timezone.utc)
    task, created = import_outreach_task_snapshot(
        status="进行中",
        event={"source": FEISHU_FULL_SAMPLE_STATUS_SOURCE, "external_id": "TASK-SOURCE-1"},
        user=records["user"],
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        source_row={
            "source": "飞书",
            "external_id": "TASK-SOURCE-1",
            "task_name": "Historical outreach",
            "start_timestamp": int(start_time.timestamp() * 1000),
            "dispatch_time": dispatch_time,
        },
        validated_data={
            "store": records["store"],
            "owner": records["user"],
            "dispatcher": records["executor"],
            "external_product_id": "PRODUCT-COMPAT-1",
            "target_count": 2,
        },
        actor=records["user"],
    )

    assert created is True
    assert task.task_no == "TASK-SOURCE-1"
    assert task.status == OutreachTask.Status.IN_PROGRESS
    assert task.dispatch_time == dispatch_time
    assert task.started_at == start_time
    assert task.outreach_at == start_time
    assert task.finalized_at is None
    assert OperationLog.objects.filter(
        tenant=records["tenant"],
        action="feishu_import_task_status",
        object_id=str(task.pk),
    ).count() == 1

    replay = import_outreach_task_snapshot(
        status="进行中",
        event={"source": FEISHU_FULL_SAMPLE_STATUS_SOURCE, "external_id": "TASK-SOURCE-1"},
        user=records["user"],
        tenant=records["tenant"],
        task=task,
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        source_row={
            "source": "飞书",
            "external_id": "TASK-SOURCE-1",
            "task_name": "Historical outreach",
            "start_timestamp": int(start_time.timestamp() * 1000),
            "dispatch_time": dispatch_time,
        },
        validated_data={
            "store": records["store"],
            "owner": records["user"],
            "dispatcher": records["executor"],
            "external_product_id": "PRODUCT-COMPAT-1",
            "target_count": 2,
        },
        actor=records["user"],
        return_metadata=True,
    )
    assert replay["task"].pk == task.pk
    assert replay["outcome"] == "noop"
    assert replay["changed"] is False


def test_task_snapshot_chronology_revision_is_audited_and_exact_replay_is_noop(sample_records):
    records = sample_records
    dispatch_time = datetime(2026, 2, 1, 8, 0, tzinfo=dt_timezone.utc)
    original_start = datetime(2026, 2, 2, 9, 30, tzinfo=dt_timezone.utc)
    revised_start = original_start + timedelta(hours=1)
    common = {
        "user": records["user"],
        "tenant": records["tenant"],
        "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        "validated_data": {
            "store": records["store"],
            "owner": records["user"],
            "dispatcher": records["executor"],
            "external_product_id": "PRODUCT-COMPAT-1",
            "target_count": 2,
        },
        "actor": records["user"],
    }
    import_outreach_task_snapshot(
        status="进行中",
        event={"source": FEISHU_FULL_SAMPLE_STATUS_SOURCE, "external_id": "TASK-CHRONOLOGY-1"},
        source_row={
            "source": "飞书",
            "external_id": "TASK-CHRONOLOGY-1",
            "start_timestamp": int(original_start.timestamp() * 1000),
            "dispatch_time": dispatch_time,
        },
        dispatch_time=dispatch_time,
        **common,
    )
    task = OutreachTask.objects.get(external_id="TASK-CHRONOLOGY-1")
    before_version = task.version
    before_updates = OperationLog.objects.filter(
        tenant=records["tenant"],
        action="feishu_import_task_update",
        object_id=str(task.pk),
    ).count()

    revised = import_outreach_task_snapshot(
        status="进行中",
        event={"source": FEISHU_FULL_SAMPLE_STATUS_SOURCE, "external_id": "TASK-CHRONOLOGY-1"},
        task=task,
        source_row={
            "source": "飞书",
            "external_id": "TASK-CHRONOLOGY-1",
            "start_timestamp": int(revised_start.timestamp() * 1000),
            "dispatch_time": dispatch_time,
        },
        dispatch_time=dispatch_time,
        return_metadata=True,
        **common,
    )
    task.refresh_from_db()
    assert revised["outcome"] == "updated"
    assert revised["changed"] is True
    assert "started_at" in revised["changed_fields"]
    assert task.version == before_version + 1
    assert task.started_at == revised_start
    update_log = OperationLog.objects.filter(
        tenant=records["tenant"],
        action="feishu_import_task_update",
        object_id=str(task.pk),
    ).latest("id")
    assert update_log.before_data["started_at"] == str(original_start)
    assert update_log.after_data["started_at"] == str(revised_start)
    assert OperationLog.objects.filter(
        tenant=records["tenant"],
        action="feishu_import_task_update",
        object_id=str(task.pk),
    ).count() == before_updates + 1

    exact_replay = import_outreach_task_snapshot(
        status="进行中",
        event={"source": FEISHU_FULL_SAMPLE_STATUS_SOURCE, "external_id": "TASK-CHRONOLOGY-1"},
        task=task,
        source_row={
            "source": "飞书",
            "external_id": "TASK-CHRONOLOGY-1",
            "start_timestamp": int(revised_start.timestamp() * 1000),
            "dispatch_time": dispatch_time,
        },
        dispatch_time=dispatch_time,
        return_metadata=True,
        **common,
    )
    task.refresh_from_db()
    assert exact_replay["outcome"] == "noop"
    assert exact_replay["changed"] is False
    assert task.version == before_version + 1
    assert OperationLog.objects.filter(
        tenant=records["tenant"],
        action="feishu_import_task_update",
        object_id=str(task.pk),
    ).count() == before_updates + 1


def _legacy_task(records, *, task_no, external_id, source="legacy_shop_analytics_bd"):
    return OutreachTask.objects.create(
        tenant=records["tenant"],
        task_no=task_no,
        task_name="Legacy task",
        store=records["store"],
        owner=records["user"],
        dispatcher=records["executor"],
        influencer=records["influencer"],
        status=OutreachTask.Status.PENDING,
        version=1,
        dispatch_time=datetime(2026, 2, 1, 8, 0, tzinfo=dt_timezone.utc),
        source=source,
        external_id=external_id,
    )


def test_task_snapshot_adopts_approved_legacy_business_number(sample_records):
    records = sample_records
    legacy = _legacy_task(
        records,
        task_no="LEGACY-TASK-NUMBER",
        external_id="LEGACY-TASK-EXTERNAL",
    )
    imported, created = import_outreach_task_snapshot(
        status="进行中",
        event={
            "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            "external_id": "NEW-TASK-EXTERNAL",
        },
        user=records["user"],
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        source_row={
            "source": "飞书",
            "external_id": "NEW-TASK-EXTERNAL",
            "task_no": "LEGACY-TASK-NUMBER",
            "dispatch_time": datetime(2026, 2, 1, 8, 0, tzinfo=dt_timezone.utc),
        },
        validated_data={
            "store": records["store"],
            "owner": records["user"],
            "dispatcher": records["executor"],
        },
        actor=records["user"],
    )
    legacy.refresh_from_db()
    assert created is False
    assert imported.pk == legacy.pk
    assert legacy.external_id == "NEW-TASK-EXTERNAL"
    assert legacy.source == FEISHU_FULL_SAMPLE_STATUS_SOURCE
    assert legacy.status == OutreachTask.Status.IN_PROGRESS


def test_task_snapshot_task_no_fallback_rejects_current_source_identity_change(sample_records):
    records = sample_records
    current = _legacy_task(
        records,
        task_no="CURRENT-TASK-NUMBER",
        external_id="CURRENT-TASK-EXTERNAL",
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
    )
    with pytest.raises(ValidationError, match="different source external id"):
        import_outreach_task_snapshot(
            status="进行中",
            event={
                "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
                "external_id": "NEW-CURRENT-TASK-EXTERNAL",
            },
            user=records["user"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            source_row={
                "source": "飞书",
                "external_id": "NEW-CURRENT-TASK-EXTERNAL",
                "task_no": "CURRENT-TASK-NUMBER",
                "dispatch_time": datetime(2026, 2, 1, 8, 0, tzinfo=dt_timezone.utc),
            },
            validated_data={
                "store": records["store"],
                "owner": records["user"],
                "dispatcher": records["executor"],
            },
            actor=records["user"],
        )
    current.refresh_from_db()
    assert current.external_id == "CURRENT-TASK-EXTERNAL"
    assert current.version == 1


def test_task_snapshot_rejects_multiple_current_legacy_external_candidates(sample_records):
    records = sample_records
    first, created = import_outreach_task_snapshot(
        status="进行中",
        event={
            "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            "external_id": "DUPLICATE-TASK-EXTERNAL",
        },
        user=records["user"],
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        source_row={
            "source": "飞书",
            "external_id": "DUPLICATE-TASK-EXTERNAL",
            "dispatch_time": datetime(2026, 2, 1, 8, 0, tzinfo=dt_timezone.utc),
        },
        validated_data={
            "store": records["store"],
            "owner": records["user"],
            "dispatcher": records["executor"],
        },
        actor=records["user"],
    )
    assert created is True
    _legacy_task(
        records,
        task_no="DUPLICATE-TASK-LEGACY",
        external_id="DUPLICATE-TASK-EXTERNAL",
    )
    with pytest.raises(ValidationError, match="Multiple current/legacy tasks"):
        import_outreach_task_snapshot(
            status="进行中",
            event={
                "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
                "external_id": "DUPLICATE-TASK-EXTERNAL",
            },
            user=records["user"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            source_row={
                "source": "飞书",
                "external_id": "DUPLICATE-TASK-EXTERNAL",
                "dispatch_time": datetime(2026, 2, 1, 8, 0, tzinfo=dt_timezone.utc),
            },
            validated_data={
                "store": records["store"],
                "owner": records["user"],
                "dispatcher": records["executor"],
            },
            actor=records["user"],
        )

def test_source_snapshot_preserves_source_costs_and_zero_quantity_placeholder(sample_records):
    records = sample_records
    fulfillment, created = import_sample_fulfillment_snapshot(
        "shipped",
        {
            "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            "source_event_id": "YPDD-SOURCE-COST-1",
            "source_status": "shipped",
        },
        {"source": FEISHU_FULL_SAMPLE_STATUS_SOURCE, "source_event_id": "YPDD-SOURCE-COST-1"},
        user=records["user"],
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        source_row={
            "source": "飞书",
            "external_id": "YPDD-SOURCE-COST-1",
            "status": "已发货",
        },
        request_key="source-cost-preservation",
        request_hash="source-cost-preservation-hash",
        validated_data={
            "fulfillment_no": "YPDD-SOURCE-COST-1",
            "influencer": records["influencer"],
            "store": records["store"],
            "owner": records["user"],
            "link_type": "direct",
            "product_name_snapshot": "Historical source product",
        },
        item_payloads=[
            {
                "site_code": "PH",
                "requested_sku": "SOURCE-SKU-0",
                "product_name": "Historical source product",
                "quantity": 0,
                "unit_cost": Decimal("12.3400"),
                "cost_amount": Decimal("0.0000"),
                "currency": "CNY",
            }
        ],
        sample_sent_at=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
        shipped_at=datetime(2026, 1, 2, tzinfo=dt_timezone.utc),
        actor=records["user"],
        source_cost_currency="CNY",
        preserve_source_cost=True,
        ignore_current_sku_price=True,
    )

    assert created is True
    item = SampleItem.objects.get(fulfillment=fulfillment)
    assert item.requested_sku == "SOURCE-SKU-0"
    assert item.quantity == 0
    assert item.unit_cost == Decimal("12.3400")
    assert item.cost_amount == Decimal("0.0000")
    assert item.currency == "CNY"
    fulfillment.refresh_from_db()
    assert fulfillment.sku_quantity == 0
    assert fulfillment.calculated_cost == Decimal("0.0000")
    assert fulfillment.status == SampleFulfillment.Status.SHIPPED


def test_non_direct_standalone_still_requires_product_id(sample_records):
    records = sample_records
    serializer = SampleFulfillmentSerializer(
        data={
            "influencer": records["influencer"].pk,
            "store": records["store"].pk,
            "link_type": "YYJL",
        }
    )

    assert serializer.is_valid() is False
    assert "external_product_id" in serializer.errors

    with pytest.raises(ValidationError, match="external_product_id"):
        create_sample_fulfillment(
            user=records["user"],
            request_key="yyjl-standalone-without-product",
            validated_data={
                "influencer": records["influencer"],
                "store": records["store"],
                "link_type": "YYJL",
            },
            item_payloads=[],
        )


def test_linked_sample_can_use_different_same_tenant_owner(sample_records):
    records = sample_records
    serializer = SampleFulfillmentSerializer(
        data={
            "outreach_task": records["task"].pk,
            "influencer": records["influencer"].pk,
            "owner": records["executor"].pk,
            "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        }
    )
    assert serializer.is_valid(), serializer.errors

    fulfillment, created = create_sample_fulfillment(
        user=records["user"],
        request_key="linked-different-owner",
        validated_data=serializer.validated_data,
        item_payloads=[],
    )

    assert created is True
    assert fulfillment.owner_id == records["executor"].pk
    assert fulfillment.outreach_task_id == records["task"].pk
    assert OutreachTask.objects.get(pk=records["task"].pk).owner_id == records["user"].pk


def test_linked_sample_owner_must_match_for_non_feishu_source(sample_records):
    records = sample_records
    with pytest.raises(ValidationError, match="owner"):
        create_sample_fulfillment(
            user=records["user"],
            request_key="linked-owner-manual-source",
            validated_data={
                "outreach_task": records["task"],
                "influencer": records["influencer"],
                "owner": records["executor"],
                "source": "manual",
            },
            item_payloads=[],
        )


def test_model_validation_keeps_owner_match_for_non_feishu_source(sample_records):
    records = sample_records
    fulfillment = SampleFulfillment(
        tenant=records["tenant"],
        fulfillment_no="MODEL-OWNER-GUARD",
        request_key="model-owner-guard",
        request_hash="a" * 64,
        outreach_task=records["task"],
        influencer=records["influencer"],
        store=records["store"],
        owner=records["executor"],
        source="manual",
    )

    with pytest.raises(DjangoValidationError, match="Owner must match"):
        fulfillment.full_clean()


def test_linked_sample_rejects_cross_tenant_owner(sample_records):
    records = sample_records

    with pytest.raises(ValidationError, match="owner"):
        create_sample_fulfillment(
            user=records["user"],
            request_key="linked-cross-tenant-owner",
            validated_data={
                "outreach_task": records["task"],
                "influencer": records["influencer"],
                "owner": records["other_user"],
            },
            item_payloads=[],
        )


def test_direct_sample_must_remain_standalone_at_model_boundary(sample_records):
    records = sample_records
    target = OutreachTarget.objects.create(
        tenant=records["tenant"],
        task=records["task"],
        influencer=records["second_influencer"],
    )
    for index, relation in enumerate(
        ({"outreach_task": records["task"]}, {"outreach_target": target}),
        start=1,
    ):
        fulfillment = SampleFulfillment(
            tenant=records["tenant"],
            fulfillment_no=f"DIRECT-LINKED-INVALID-{index}",
            request_key=f"direct-linked-invalid-{index}",
            request_hash="hash",
            influencer=records["second_influencer"],
            store=records["store"],
            owner=records["user"],
            link_type="direct",
            quick_tags=[],
            **relation,
        )

        with pytest.raises(DjangoValidationError) as exc_info:
            fulfillment.full_clean()

        assert "link_type" in exc_info.value.message_dict


def test_sample_serializer_partial_update_keeps_existing_relations_and_type(sample_records):
    records = sample_records
    fulfillment, _ = create_sample_fulfillment(
        user=records["user"],
        request_key="partial-serializer-compatibility",
        validated_data={
            "influencer": records["influencer"],
            "store": records["store"],
            "link_type": "direct",
        },
        item_payloads=[],
    )

    serializer = SampleFulfillmentSerializer(
        fulfillment,
        data={"notes": "partial edit"},
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("store", "second_store"),
        ("influencer", "second_influencer"),
        ("external_product_id", "PRODUCT-COMPAT-OTHER"),
    ],
)
def test_linked_sample_owner_relaxation_keeps_other_relation_constraints(
    sample_records, field, value
):
    records = sample_records
    payload = {
        "outreach_task": records["task"],
        "influencer": records["influencer"],
        "owner": records["executor"],
        "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
    }
    payload[field] = records[value] if value in records else value

    with pytest.raises(ValidationError, match=field):
        create_sample_fulfillment(
            user=records["user"],
            request_key=f"linked-invalid-{field}",
            validated_data=payload,
            item_payloads=[],
        )


def _source_sample(records, request_key):
    fulfillment, _ = create_sample_fulfillment(
        user=records["user"],
        request_key=request_key,
        validated_data={
            "influencer": records["influencer"],
            "store": records["store"],
            "link_type": "direct",
            "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        },
        item_payloads=[],
    )
    return fulfillment


def _bare_source_sample(records, *, source, external_id, fulfillment_no):
    return SampleFulfillment.objects.create(
        tenant=records["tenant"],
        fulfillment_no=fulfillment_no,
        request_key=f"{source}:{fulfillment_no}",
        request_hash="c" * 64,
        influencer=records["influencer"],
        store=records["store"],
        owner=records["user"],
        link_type="direct",
        quick_tags=[],
        source=source,
        external_id=external_id,
    )


def test_source_row_import_rejects_allowed_source_external_id_duplicates(sample_records):
    records = sample_records
    _bare_source_sample(
        records,
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        external_id="DUPLICATE-SOURCE-ID",
        fulfillment_no="DUPLICATE-SOURCE-ID",
    )
    _bare_source_sample(
        records,
        source="legacy_shop_analytics_bd",
        external_id="DUPLICATE-SOURCE-ID",
        fulfillment_no="DUPLICATE-SOURCE-ID-LEGACY",
    )

    with pytest.raises(ValidationError, match="Multiple current/legacy fulfillments"):
        import_sample_fulfillment_snapshot(
            "pending",
            {
                "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
                "id": "DUPLICATE-SOURCE-ID",
                "status": "pending",
            },
            None,
            user=records["user"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            validated_data={
                "fulfillment_no": "DUPLICATE-SOURCE-ID",
                "influencer": records["influencer"],
                "store": records["store"],
                "owner": records["user"],
                "link_type": "direct",
            },
            item_payloads=[],
            sample_sent_at=datetime(2026, 9, 1, tzinfo=dt_timezone.utc),
            actor=records["user"],
        )


def test_source_row_import_rejects_existing_external_business_number_mismatch(sample_records):
    records = sample_records
    _bare_source_sample(
        records,
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        external_id="SOURCE-ID-NUMBER-MISMATCH",
        fulfillment_no="LEGACY-BUSINESS-NO",
    )

    with pytest.raises(ValidationError, match="Existing source fulfillment number"):
        import_sample_fulfillment_snapshot(
            "pending",
            {
                "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
                "id": "SOURCE-ID-NUMBER-MISMATCH",
                "status": "pending",
            },
            None,
            user=records["user"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            validated_data={
                "fulfillment_no": "SOURCE-ID-NUMBER-MISMATCH",
                "influencer": records["influencer"],
                "store": records["store"],
                "owner": records["user"],
                "link_type": "direct",
            },
            item_payloads=[],
            sample_sent_at=datetime(2026, 9, 1, tzinfo=dt_timezone.utc),
            actor=records["user"],
        )


def test_source_row_import_adopts_approved_legacy_business_number_and_items(sample_records):
    records = sample_records
    legacy = _bare_source_sample(
        records,
        source="legacy_shop_analytics_bd",
        external_id="LEGACY-SAMPLE-EXTERNAL",
        fulfillment_no="SOURCE-SAMPLE-NUMBER",
    )
    item = SampleItem.objects.create(
        tenant=records["tenant"],
        fulfillment=legacy,
        external_product_id="PRODUCT-COMPAT-1",
        site_code="PH",
        requested_sku="SOURCE-SKU-1",
        product_name="Legacy product",
        quantity=1,
        unit_cost=Decimal("1.0000"),
        cost_amount=Decimal("1.0000"),
        currency="CNY",
        cost_source="legacy_shop_analytics_bd",
    )

    imported, created = import_sample_fulfillment_snapshot(
        "shipped",
        {
            "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            "id": "SOURCE-SAMPLE-NUMBER",
            "status": "shipped",
        },
        None,
        user=records["user"],
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        request_key=f"{FEISHU_FULL_SAMPLE_STATUS_SOURCE}:sample:SOURCE-SAMPLE-NUMBER",
        request_hash="d" * 64,
        validated_data={
            "fulfillment_no": "SOURCE-SAMPLE-NUMBER",
            "influencer": records["influencer"],
            "store": records["store"],
            "owner": records["user"],
            "link_type": "direct",
            "external_product_id": "PRODUCT-COMPAT-1",
            "product_name_snapshot": "Imported product",
        },
        item_payloads=[
            {
                "external_product_id": "PRODUCT-COMPAT-1",
                "site_code": "PH",
                "requested_sku": "SOURCE-SKU-1",
                "product_name": "Imported product",
                "quantity": 2,
                "unit_cost": Decimal("2.0000"),
                "cost_amount": Decimal("4.0000"),
            }
        ],
        sample_sent_at=datetime(2026, 9, 1, tzinfo=dt_timezone.utc),
        shipped_at=datetime(2026, 9, 2, tzinfo=dt_timezone.utc),
        actor=records["user"],
    )

    legacy.refresh_from_db()
    item.refresh_from_db()
    assert created is False
    assert imported.pk == legacy.pk
    assert legacy.source == FEISHU_FULL_SAMPLE_STATUS_SOURCE
    assert legacy.external_id == "SOURCE-SAMPLE-NUMBER"
    assert legacy.status == SampleFulfillment.Status.SHIPPED
    assert item.cost_source == FEISHU_FULL_SAMPLE_STATUS_SOURCE
    assert item.quantity == 2
    assert item.cost_amount == Decimal("4.0000")


def test_source_row_import_rejects_current_source_number_identity_change(sample_records):
    records = sample_records
    current = _bare_source_sample(
        records,
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        external_id="CURRENT-SAMPLE-EXTERNAL",
        fulfillment_no="CURRENT-SAMPLE-NUMBER",
    )

    with pytest.raises(ValidationError, match="different source external id"):
        import_sample_fulfillment_snapshot(
            "pending",
            {
                "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
                "id": "CURRENT-SAMPLE-NUMBER",
                "status": "pending",
            },
            None,
            user=records["user"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            validated_data={
                "fulfillment_no": "CURRENT-SAMPLE-NUMBER",
                "influencer": records["influencer"],
                "store": records["store"],
                "owner": records["user"],
                "link_type": "direct",
            },
            item_payloads=[],
            sample_sent_at=datetime(2026, 9, 1, tzinfo=dt_timezone.utc),
            actor=records["user"],
        )
    current.refresh_from_db()
    assert current.external_id == "CURRENT-SAMPLE-EXTERNAL"


def test_source_status_import_is_audited_monotonic_and_idempotent(sample_records):
    records = sample_records
    fulfillment = _source_sample(records, "source-status-import")
    event = {
        "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        "source_event_id": "sample-row-1",
        "source_observed_at": "2026-09-01T08:30:00+08:00",
    }
    first = import_sample_fulfillment_snapshot(
        "published",
        event,
        {"source": FEISHU_FULL_SAMPLE_STATUS_SOURCE},
        user=records["executor"],
        fulfillment=fulfillment,
    )
    assert first.status == SampleFulfillment.Status.PUBLISHED
    assert first.version == 2
    first.refresh_from_db()
    assert first.shipped_at.isoformat().startswith("2026-09-01T00:30:00")

    second = import_sample_fulfillment_snapshot(
        "published",
        event,
        {"source": FEISHU_FULL_SAMPLE_STATUS_SOURCE},
        user=records["executor"],
        fulfillment=fulfillment,
    )
    assert second.status == SampleFulfillment.Status.PUBLISHED
    assert second.version == 2
    assert FulfillmentStatusEvent.objects.filter(
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        source_event_id="sample-row-1",
    ).count() == 1
    assert OperationLog.objects.filter(
        tenant=records["tenant"],
        action="sample_status_import",
        object_id=str(fulfillment.pk),
    ).count() == 1


def test_source_status_import_preserves_published_for_stale_shipped_snapshot(sample_records):
    records = sample_records
    fulfillment = _source_sample(records, "source-status-preserve-published")
    fulfillment.status = SampleFulfillment.Status.PUBLISHED
    # Bypass the guarded model save only to construct the already-published
    # fixture; the import service itself remains the only state write path.
    from django.db.models.query import QuerySet

    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        status=SampleFulfillment.Status.PUBLISHED,
        version=2,
    )
    fulfillment.refresh_from_db()

    imported = import_sample_fulfillment_snapshot(
        "shipped",
        {
            "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            "source_event_id": "sample-row-stale",
        },
        None,
        user=records["executor"],
        fulfillment=fulfillment,
    )
    assert imported.status == SampleFulfillment.Status.PUBLISHED
    assert imported.version == 2
    event = FulfillmentStatusEvent.objects.get(source_event_id="sample-row-stale")
    assert event.source_status == SampleFulfillment.Status.SHIPPED
    assert event.to_status == SampleFulfillment.Status.PUBLISHED


def test_source_status_replay_of_old_shipped_event_after_published_is_noop(sample_records):
    records = sample_records
    fulfillment = _source_sample(records, "source-status-old-event-replay")
    old_event = {
        "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        "source_event_id": "source-status-old-shipped",
    }
    import_sample_fulfillment_snapshot(
        "shipped",
        old_event,
        None,
        user=records["executor"],
        fulfillment=fulfillment,
    )
    import_sample_fulfillment_snapshot(
        "published",
        {
            "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            "source_event_id": "source-status-new-published",
        },
        None,
        user=records["executor"],
        fulfillment=fulfillment,
    )
    fulfillment.refresh_from_db()
    published_version = fulfillment.version
    event_count = FulfillmentStatusEvent.objects.filter(
        tenant=records["tenant"],
        fulfillment=fulfillment,
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
    ).count()
    log_count = OperationLog.objects.filter(
        tenant=records["tenant"],
        action="sample_status_import",
        object_id=str(fulfillment.pk),
    ).count()

    replay = import_sample_fulfillment_snapshot(
        "shipped",
        old_event,
        None,
        user=records["executor"],
        fulfillment=fulfillment,
        return_metadata=True,
    )
    fulfillment.refresh_from_db()
    assert replay["outcome"] == "noop"
    assert replay["changed"] is False
    assert fulfillment.status == SampleFulfillment.Status.PUBLISHED
    assert fulfillment.version == published_version
    assert FulfillmentStatusEvent.objects.filter(
        tenant=records["tenant"],
        fulfillment=fulfillment,
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
    ).count() == event_count
    assert OperationLog.objects.filter(
        tenant=records["tenant"],
        action="sample_status_import",
        object_id=str(fulfillment.pk),
    ).count() == log_count


def test_source_status_replay_rejects_corrupt_historical_event_target(sample_records):
    records = sample_records
    fulfillment = _source_sample(records, "source-status-corrupt-event")
    event_id = "source-status-corrupt-event-shipped"
    import_sample_fulfillment_snapshot(
        "shipped",
        {
            "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            "source_event_id": event_id,
        },
        None,
        user=records["executor"],
        fulfillment=fulfillment,
    )
    from django.db.models.query import QuerySet

    QuerySet.update(
        FulfillmentStatusEvent.objects.filter(
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            source_event_id=event_id,
        ),
        to_status=SampleFulfillment.Status.PUBLISHED,
    )
    with pytest.raises(ValidationError, match="already imported"):
        import_sample_fulfillment_snapshot(
            "shipped",
            {
                "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
                "source_event_id": event_id,
            },
            None,
            user=records["executor"],
            fulfillment=fulfillment,
        )


def test_source_status_import_rejects_mismatched_source_tenant_and_replay_status(sample_records):
    records = sample_records
    fulfillment = _source_sample(records, "source-status-strict")
    with pytest.raises(ValidationError, match="source"):
        import_sample_fulfillment_snapshot(
            "shipped",
            {"source": "manual", "source_event_id": "strict-1"},
            None,
            user=records["executor"],
            fulfillment=fulfillment,
        )

    import_sample_fulfillment_snapshot(
        "shipped",
        {"source": FEISHU_FULL_SAMPLE_STATUS_SOURCE, "source_event_id": "strict-2"},
        None,
        user=records["executor"],
        fulfillment=fulfillment,
    )
    with pytest.raises(ValidationError) as exc_info:
        import_sample_fulfillment_snapshot(
            "published",
            {"source": FEISHU_FULL_SAMPLE_STATUS_SOURCE, "source_event_id": "strict-2"},
            None,
            user=records["executor"],
            fulfillment=fulfillment,
        )
    assert exc_info.value.get_codes() == {"event": "conflict"}


def test_fulfillment_status_event_import_identity_is_all_or_none(sample_records):
    records = sample_records
    fulfillment = _source_sample(records, "source-status-event-clean")
    partial = FulfillmentStatusEvent(
        tenant=records["tenant"],
        fulfillment=fulfillment,
        from_status=SampleFulfillment.Status.PENDING,
        to_status=SampleFulfillment.Status.SHIPPED,
        actor=records["executor"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
    )
    with pytest.raises(DjangoValidationError) as exc_info:
        partial.full_clean()
    assert "source" in exc_info.value.message_dict


def test_source_row_import_api_upserts_source_number_and_uses_explicit_dates(sample_records):
    records = sample_records
    result = import_sample_fulfillment_snapshot(
        "published",
        {"source": "飞书", "id": "SOURCE-ROW-API", "status": "已发布"},
        user=records["executor"],
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        request_key=f"{FEISHU_FULL_SAMPLE_STATUS_SOURCE}:sample:SOURCE-ROW-API",
        request_hash="a" * 64,
        validated_data={
            "fulfillment_no": "SOURCE-ROW-API",
            "influencer": records["influencer"],
            "store": records["store"],
            "owner": records["executor"],
            "link_type": "direct",
        },
        item_payloads=[],
        sample_sent_at=datetime(2026, 9, 1, tzinfo=dt_timezone.utc),
        shipped_at=datetime(2026, 9, 2, tzinfo=dt_timezone.utc),
        actor=records["executor"],
        operation_log=True,
    )
    fulfillment, created = result
    assert created is True
    assert fulfillment.fulfillment_no == "SOURCE-ROW-API"
    assert fulfillment.source == FEISHU_FULL_SAMPLE_STATUS_SOURCE
    assert fulfillment.external_id == "SOURCE-ROW-API"
    assert fulfillment.status == SampleFulfillment.Status.PUBLISHED
    fulfillment.refresh_from_db()
    assert fulfillment.sample_sent_at == datetime(2026, 9, 1, tzinfo=dt_timezone.utc)
    assert fulfillment.shipped_at == datetime(2026, 9, 2, tzinfo=dt_timezone.utc)
    snapshot = BdSampleAttributionSnapshot.objects.get(fulfillment=fulfillment)
    assert snapshot.sampled_at == fulfillment.sample_sent_at
    assert snapshot.shipped_at == fulfillment.shipped_at
    assert snapshot.sample_status == fulfillment.status
    assert snapshot.currency == "CNY"
    assert snapshot.site == records["store"].country_code
    assert snapshot.source == FEISHU_FULL_SAMPLE_STATUS_SOURCE


def test_source_row_import_preserves_source_cost_facts_and_replay(sample_records):
    records = sample_records
    item_payload = {
        "external_product_id": "PRODUCT-SOURCE-COST",
        "site_code": "PH",
        "requested_sku": "SRC-SKU-1",
        "product_name": "Source product",
        "quantity": 2,
        "unit_cost": "4.2500",
        "cost_amount": "8.5000",
        "currency": "USD",
        "cost_source": "live-catalog",
        "sales_amount": "99.00",
    }
    kwargs = {
        "user": records["executor"],
        "tenant": records["tenant"],
        "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        "source_row": {
            "source": "飞书",
            "id": "SOURCE-COST-ROW",
            "status": "已发货",
        },
        "request_key": f"{FEISHU_FULL_SAMPLE_STATUS_SOURCE}:sample:SOURCE-COST-ROW",
        "request_hash": "b" * 64,
        "validated_data": {
            "fulfillment_no": "SOURCE-COST-ROW",
            "influencer": records["influencer"],
            "store": records["store"],
            "owner": records["executor"],
            "link_type": "direct",
            "external_product_id": "PRODUCT-SOURCE-COST",
        },
        "item_payloads": [item_payload],
        "status": "shipped",
        "sample_sent_at": datetime(2026, 9, 1, tzinfo=dt_timezone.utc),
        "shipped_at": datetime(2026, 9, 2, tzinfo=dt_timezone.utc),
        "actor": records["executor"],
        "operation_log": True,
    }
    fulfillment, created = import_sample_fulfillment_snapshot(**kwargs)
    assert created is True
    item = fulfillment.items.get()
    assert item.unit_cost == Decimal("4.2500")
    assert item.cost_amount == Decimal("8.5000")
    assert item.currency == "CNY"
    assert item.cost_source == FEISHU_FULL_SAMPLE_STATUS_SOURCE
    assert item.sales_amount is None
    assert fulfillment.calculated_cost == Decimal("8.5000")
    assert fulfillment.video_deadline_at == datetime(2026, 9, 22, tzinfo=dt_timezone.utc)
    item_id = item.pk
    fulfillment.refresh_from_db()
    replay_version = fulfillment.version
    replay_updated_at = fulfillment.updated_at
    replay_result = import_sample_fulfillment_snapshot(
        **kwargs,
        return_metadata=True,
    )
    replay = replay_result["fulfillment"]
    assert replay_result["created"] is False
    assert replay_result["outcome"] == "noop"
    assert replay_result["changed"] is False
    assert replay.pk == fulfillment.pk
    assert replay.items.get().pk == item_id
    assert replay.version == replay_version
    assert replay.updated_at == replay_updated_at
    assert FulfillmentStatusEvent.objects.filter(
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        source_event_id="SOURCE-COST-ROW:shipped",
    ).count() == 1
    assert OperationLog.objects.filter(
        tenant=records["tenant"],
        action="sample_status_import",
        object_id=str(fulfillment.pk),
    ).count() == 1


def test_source_cleanup_soft_deletes_only_missing_source_rows_and_replays_idempotently(sample_records):
    records = sample_records
    fulfillment = _source_sample(records, "source-cleanup-sample")
    keep = _source_sample(records, "source-cleanup-keep")
    from django.db.models.query import QuerySet

    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        external_id="SOURCE-CLEANUP-ROW",
    )
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=keep.pk),
        external_id="SOURCE-CLEANUP-KEEP",
    )
    fulfillment.refresh_from_db()
    keep.refresh_from_db()
    manifest_digest = _import_manifest_digest(
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        task_external_ids=set(),
        sample_external_ids={"SOURCE-CLEANUP-KEEP"},
    )
    batch = ImportBatch.objects.create(
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        batch_key="source-cleanup-batch",
        status=ImportBatch.Status.COMPLETED,
        manifest_digest=manifest_digest,
        created_by=records["executor"],
    )

    first = soft_delete_import_source(
        user=records["executor"],
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        batch=batch,
        task_external_ids=set(),
        sample_external_ids={"SOURCE-CLEANUP-KEEP"},
        reason="missing-from-source",
    )
    fulfillment.refresh_from_db()
    keep.refresh_from_db()
    assert first["sample_deleted"] == 1
    assert fulfillment.is_deleted is True
    assert keep.is_deleted is False
    assert OperationLog.objects.filter(
        tenant=records["tenant"],
        action="feishu_import_source_soft_delete",
    ).count() == 1

    second = soft_delete_import_source(
        user=records["executor"],
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        batch=batch,
        task_external_ids=set(),
        sample_external_ids={"SOURCE-CLEANUP-KEEP"},
        reason="missing-from-source",
    )
    assert second["replayed"] is True
    assert OperationLog.objects.filter(
        tenant=records["tenant"],
        action="feishu_import_source_soft_delete",
    ).count() == 1


@pytest.mark.parametrize("status", [ImportBatch.Status.PENDING, ImportBatch.Status.FAILED])
def test_source_cleanup_requires_persisted_completed_batch(sample_records, status):
    records = sample_records
    fulfillment = _source_sample(records, f"source-cleanup-{status}")
    from django.db.models.query import QuerySet

    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        external_id=f"SOURCE-CLEANUP-{status}",
    )
    manifest_digest = _import_manifest_digest(
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        task_external_ids=set(),
        sample_external_ids={"SOURCE-CLEANUP-KEEP"},
    )
    batch = ImportBatch.objects.create(
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        batch_key=f"source-cleanup-{status}",
        status=status,
        manifest_digest=manifest_digest,
        created_by=records["executor"],
    )

    with pytest.raises(ValidationError, match="persisted completed import batch"):
        soft_delete_import_source(
            user=records["executor"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            batch=batch,
            task_external_ids=set(),
            sample_external_ids={"SOURCE-CLEANUP-KEEP"},
        )
    fulfillment.refresh_from_db()
    assert fulfillment.is_deleted is False
    assert OperationLog.objects.filter(
        tenant=records["tenant"],
        action="feishu_import_source_soft_delete",
    ).count() == 0


@pytest.mark.parametrize(
    "terminal_status",
    [OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED],
)
def test_feishu_target_snapshot_materializes_terminal_task_history_idempotently(
    sample_records, terminal_status
):
    records = sample_records
    from django.db.models.query import QuerySet

    QuerySet.update(
        OutreachTask.objects.filter(pk=records["task"].pk),
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        external_id="FEISHU-TASK-HISTORY-1",
        status=terminal_status,
        version=4,
    )
    records["task"].refresh_from_db()
    linked_at = datetime(2026, 8, 1, 9, 30, tzinfo=dt_timezone.utc)
    kwargs = {
        "user": records["user"],
        "actor": records["user"],
        "tenant": records["tenant"],
        "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        "task": records["task"],
        "influencer": records["second_influencer"],
        "source_task_external_id": "FEISHU-TASK-HISTORY-1",
        "source_sample_external_id": "FEISHU-SAMPLE-HISTORY-1",
        "first_linked_at": linked_at,
        "return_metadata": True,
    }

    first = import_outreach_target_snapshot(**kwargs)
    replay = import_outreach_target_snapshot(**kwargs)

    assert first["outcome"] == "created"
    assert replay["outcome"] == "noop"
    assert OutreachTarget.objects.filter(
        tenant=records["tenant"],
        task=records["task"],
        influencer=records["second_influencer"],
        is_deleted=False,
    ).count() == 1
    log = OperationLog.objects.get(
        tenant=records["tenant"],
        action="feishu_import_target_create",
        object_id=str(first["target"].pk),
    )
    assert log.after_data["historical_terminal_exception"] is True
    assert log.after_data["source_sample_external_id"] == "FEISHU-SAMPLE-HISTORY-1"


def test_feishu_target_snapshot_keeps_source_boundary(sample_records):
    records = sample_records
    from django.db.models.query import QuerySet

    QuerySet.update(
        OutreachTask.objects.filter(pk=records["task"].pk),
        source="manual",
        external_id="FEISHU-TASK-FOREIGN",
        status=OutreachTask.Status.COMPLETED,
    )
    records["task"].refresh_from_db()

    with pytest.raises(ValidationError, match="another source"):
        import_outreach_target_snapshot(
            user=records["user"],
            actor=records["user"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            task=records["task"],
            influencer=records["second_influencer"],
            source_task_external_id="FEISHU-TASK-FOREIGN",
            source_sample_external_id="FEISHU-SAMPLE-FOREIGN",
            first_linked_at=datetime(2026, 8, 1, tzinfo=dt_timezone.utc),
        )
    QuerySet.update(
        OutreachTask.objects.filter(pk=records["task"].pk),
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        external_id="FEISHU-TASK-FOREIGN",
    )
    records["task"].refresh_from_db()
    other_influencer = Influencer.objects.create(
        tenant=records["other_user"].tenant,
        code="other-tenant-target-influencer",
        name="Other tenant target influencer",
        platform="tiktok",
    )
    with pytest.raises(ValidationError, match="current tenant"):
        import_outreach_target_snapshot(
            user=records["user"],
            actor=records["user"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            task=records["task"],
            influencer=other_influencer,
            source_task_external_id="FEISHU-TASK-FOREIGN",
            source_sample_external_id="FEISHU-SAMPLE-FOREIGN",
            first_linked_at=datetime(2026, 8, 1, tzinfo=dt_timezone.utc),
        )
    assert not OutreachTarget.objects.filter(
        task=records["task"],
        influencer=records["second_influencer"],
    ).exists()


def test_feishu_target_snapshot_restore_audit_matches_persisted_link_time(sample_records):
    records = sample_records
    from django.db.models.query import QuerySet

    persisted_linked_at = datetime(2026, 7, 1, 8, 0, tzinfo=dt_timezone.utc)
    supplied_linked_at = datetime(2026, 8, 1, 9, 30, tzinfo=dt_timezone.utc)
    target = OutreachTarget.objects.create(
        tenant=records["tenant"],
        task=records["task"],
        influencer=records["second_influencer"],
        first_linked_at=persisted_linked_at,
    )
    QuerySet.update(
        OutreachTarget.objects.filter(pk=target.pk),
        is_deleted=True,
        deleted_at=datetime(2026, 8, 2, tzinfo=dt_timezone.utc),
    )
    QuerySet.update(
        OutreachTask.objects.filter(pk=records["task"].pk),
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        external_id="FEISHU-TASK-RESTORE-AUDIT",
        status=OutreachTask.Status.COMPLETED,
    )
    records["task"].refresh_from_db()

    result = import_outreach_target_snapshot(
        user=records["user"],
        actor=records["user"],
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        task=records["task"],
        influencer=records["second_influencer"],
        source_task_external_id="FEISHU-TASK-RESTORE-AUDIT",
        source_sample_external_id="FEISHU-SAMPLE-RESTORE-AUDIT",
        first_linked_at=supplied_linked_at,
        return_metadata=True,
    )

    target.refresh_from_db()
    assert result["outcome"] == "restored"
    assert target.first_linked_at == persisted_linked_at
    log = OperationLog.objects.get(
        tenant=records["tenant"],
        action="feishu_import_target_restore",
        object_id=str(target.pk),
    )
    assert log.after_data["first_linked_at"] == persisted_linked_at.isoformat()
    assert log.after_data["source_first_linked_at"] == supplied_linked_at.isoformat()


@pytest.mark.parametrize(
    "preserved_status",
    [
        SampleFulfillment.Status.COMPLETED,
        SampleFulfillment.Status.CANCELLED,
        SampleFulfillment.Status.LIVE_CREATOR,
        SampleFulfillment.Status.BLACKLISTED,
    ],
)
def test_source_status_import_preserves_terminal_and_creator_managed_states(
    sample_records, preserved_status
):
    records = sample_records
    from django.db.models.query import QuerySet

    fulfillment = _source_sample(records, f"preserved-{preserved_status}")
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        status=preserved_status,
        version=7,
    )
    fulfillment.refresh_from_db()
    event = {
        "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        "source_event_id": f"preserved-{preserved_status}-shipped",
    }

    imported = import_sample_fulfillment_snapshot(
        "shipped",
        event,
        None,
        user=records["executor"],
        fulfillment=fulfillment,
    )
    replay = import_sample_fulfillment_snapshot(
        "shipped",
        event,
        None,
        user=records["executor"],
        fulfillment=fulfillment,
        return_metadata=True,
    )

    imported.refresh_from_db()
    assert imported.status == preserved_status
    assert imported.version == 7
    assert replay["outcome"] == "noop"
    status_event = FulfillmentStatusEvent.objects.get(
        tenant=records["tenant"],
        source_event_id=f"preserved-{preserved_status}-shipped",
    )
    assert status_event.from_status == preserved_status
    assert status_event.to_status == preserved_status
    log = OperationLog.objects.get(
        tenant=records["tenant"],
        action="sample_status_import",
        object_id=str(fulfillment.pk),
    )
    assert log.after_data["preserved"] is True


def test_source_row_import_updates_legacy_facts_but_preserves_blacklisted_state(sample_records):
    records = sample_records
    from django.db.models.query import QuerySet

    legacy = _bare_source_sample(
        records,
        source="legacy_shop_analytics_bd",
        external_id="LEGACY-BLACKLISTED-EXTERNAL",
        fulfillment_no="FEISHU-BLACKLISTED-1",
    )
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=legacy.pk),
        status=SampleFulfillment.Status.BLACKLISTED,
        version=5,
    )
    legacy.refresh_from_db()

    result = import_sample_fulfillment_snapshot(
        "shipped",
        {
            "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            "id": "FEISHU-BLACKLISTED-1",
            "status": "shipped",
        },
        None,
        user=records["user"],
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        request_key=f"{FEISHU_FULL_SAMPLE_STATUS_SOURCE}:sample:FEISHU-BLACKLISTED-1",
        request_hash="e" * 64,
        validated_data={
            "fulfillment_no": "FEISHU-BLACKLISTED-1",
            "influencer": records["influencer"],
            "store": records["store"],
            "owner": records["user"],
            "link_type": "direct",
            "external_product_id": "BLACKLISTED-PRODUCT",
            "product_name_snapshot": "Blacklisted source product",
        },
        item_payloads=[
            {
                "site_code": "PH",
                "requested_sku": "BLACKLISTED-SKU",
                "product_name": "Blacklisted source product",
                "quantity": 1,
                "unit_cost": Decimal("3.0000"),
                "cost_amount": Decimal("3.0000"),
            }
        ],
        sample_sent_at=datetime(2026, 8, 1, tzinfo=dt_timezone.utc),
        shipped_at=datetime(2026, 8, 2, tzinfo=dt_timezone.utc),
        actor=records["user"],
        return_metadata=True,
    )

    legacy.refresh_from_db()
    assert result["outcome"] == "updated"
    assert legacy.source == FEISHU_FULL_SAMPLE_STATUS_SOURCE
    assert legacy.external_id == "FEISHU-BLACKLISTED-1"
    assert legacy.status == SampleFulfillment.Status.BLACKLISTED
    assert legacy.version == 6
    assert SampleItem.objects.get(fulfillment=legacy).requested_sku == "BLACKLISTED-SKU"


def test_pending_source_row_preserves_existing_terminal_shipping_chronology(sample_records):
    records = sample_records
    from django.db.models.query import QuerySet

    shipped_at = datetime(2026, 7, 5, 10, 0, tzinfo=dt_timezone.utc)
    legacy = _bare_source_sample(
        records,
        source="legacy_shop_analytics_bd",
        external_id="LEGACY-TERMINAL-CHRONOLOGY",
        fulfillment_no="FEISHU-TERMINAL-CHRONOLOGY",
    )
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=legacy.pk),
        status=SampleFulfillment.Status.BLACKLISTED,
        shipped_at=shipped_at,
        video_deadline_at=shipped_at + timedelta(days=20),
        version=5,
    )
    legacy.refresh_from_db()

    result = import_sample_fulfillment_snapshot(
        "pending",
        {
            "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            "id": "FEISHU-TERMINAL-CHRONOLOGY",
            "status": "pending",
        },
        None,
        user=records["user"],
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        request_key=(
            f"{FEISHU_FULL_SAMPLE_STATUS_SOURCE}:sample:FEISHU-TERMINAL-CHRONOLOGY"
        ),
        request_hash="f" * 64,
        validated_data={
            "fulfillment_no": "FEISHU-TERMINAL-CHRONOLOGY",
            "influencer": records["influencer"],
            "store": records["store"],
            "owner": records["user"],
            "link_type": "direct",
        },
        item_payloads=[],
        sample_sent_at=datetime(2026, 7, 1, tzinfo=dt_timezone.utc),
        shipped_at=None,
        actor=records["user"],
        return_metadata=True,
    )

    legacy.refresh_from_db()
    assert result["outcome"] == "updated"
    assert legacy.status == SampleFulfillment.Status.BLACKLISTED
    assert legacy.shipped_at == shipped_at
    assert legacy.video_deadline_at == shipped_at + timedelta(days=20)


def test_historical_status_event_replay_after_terminal_progress_is_noop(sample_records):
    records = sample_records
    from django.db.models.query import QuerySet

    fulfillment = _source_sample(records, "historical-event-then-completed")
    event = {
        "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        "source_event_id": "historical-event-then-completed-shipped",
    }
    import_sample_fulfillment_snapshot(
        "shipped",
        event,
        None,
        user=records["executor"],
        fulfillment=fulfillment,
    )
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        status=SampleFulfillment.Status.COMPLETED,
        version=9,
    )

    replay = import_sample_fulfillment_snapshot(
        "shipped",
        event,
        None,
        user=records["executor"],
        fulfillment=fulfillment,
        return_metadata=True,
    )

    fulfillment.refresh_from_db()
    assert replay["outcome"] == "noop"
    assert fulfillment.status == SampleFulfillment.Status.COMPLETED
    assert fulfillment.version == 9


def test_source_status_import_still_rejects_unknown_existing_state(sample_records):
    records = sample_records
    from django.db.models.query import QuerySet

    fulfillment = _source_sample(records, "unknown-source-status")
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        status="future_unknown_state",
    )
    fulfillment.refresh_from_db()

    with pytest.raises(ValidationError, match="Terminal or creator-managed"):
        import_sample_fulfillment_snapshot(
            "shipped",
            {
                "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
                "source_event_id": "unknown-source-status-shipped",
            },
            None,
            user=records["executor"],
            fulfillment=fulfillment,
        )


def test_source_cleanup_rejects_persisted_and_supplied_manifest_digest_mismatch(sample_records):
    records = sample_records
    fulfillment = _source_sample(records, "source-cleanup-digest-mismatch")
    from django.db.models.query import QuerySet

    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        external_id="SOURCE-CLEANUP-DIGEST-MISSING",
    )
    persisted_ids = {"SOURCE-CLEANUP-DIGEST-PRESENT"}
    persisted_digest = _import_manifest_digest(
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        task_external_ids=set(),
        sample_external_ids=persisted_ids,
    )
    batch = ImportBatch.objects.create(
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        batch_key="source-cleanup-digest-mismatch-batch",
        status=ImportBatch.Status.COMPLETED,
        manifest_digest=persisted_digest,
        created_by=records["executor"],
    )

    with pytest.raises(ValidationError, match="does not match the persisted") as persisted_error:
        soft_delete_import_source(
            user=records["executor"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            batch=batch,
            task_external_ids=set(),
            sample_external_ids={"SOURCE-CLEANUP-DIGEST-OTHER"},
        )
    assert persisted_error.value.get_codes() == {"manifest": "conflict"}

    with pytest.raises(ValidationError, match="Supplied cleanup manifest digest") as supplied_error:
        soft_delete_import_source(
            user=records["executor"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            batch=batch,
            task_external_ids=set(),
            sample_external_ids=persisted_ids,
            manifest_digest="f" * 64,
        )
    assert supplied_error.value.get_codes() == {"manifest": "conflict"}
    fulfillment.refresh_from_db()
    assert fulfillment.is_deleted is False
    assert OperationLog.objects.filter(
        tenant=records["tenant"],
        action="feishu_import_source_soft_delete",
    ).count() == 0


def test_source_cleanup_rejects_manifest_digest_mismatch_without_writes(sample_records):
    records = sample_records
    fulfillment = _source_sample(records, "source-cleanup-manifest-mismatch")
    from django.db.models.query import QuerySet

    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        external_id="SOURCE-CLEANUP-MANIFEST-MISMATCH",
    )
    persisted_digest = _import_manifest_digest(
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        task_external_ids=set(),
        sample_external_ids={"SOURCE-CLEANUP-MANIFEST-MISMATCH"},
    )
    batch = ImportBatch.objects.create(
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        batch_key="source-cleanup-manifest-mismatch-batch",
        status=ImportBatch.Status.COMPLETED,
        manifest_digest=persisted_digest,
        created_by=records["executor"],
    )

    # A different reconciliation set cannot reuse this completed batch.
    with pytest.raises(ValidationError, match="does not match the persisted completed import batch"):
        soft_delete_import_source(
            user=records["executor"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            batch=batch,
            task_external_ids=set(),
            sample_external_ids={"SOURCE-CLEANUP-OTHER-MANIFEST"},
        )
    fulfillment.refresh_from_db()
    assert fulfillment.is_deleted is False
    # Even with matching IDs, a caller-supplied digest is independently
    # checked so it cannot be used to smuggle a different manifest through.
    with pytest.raises(ValidationError, match="Supplied cleanup manifest digest"):
        soft_delete_import_source(
            user=records["executor"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            batch=batch,
            task_external_ids=set(),
            sample_external_ids={"SOURCE-CLEANUP-MANIFEST-MISMATCH"},
            manifest_digest="0" * 64,
        )
    fulfillment.refresh_from_db()
    assert fulfillment.is_deleted is False


def test_source_cleanup_rejects_fake_batch_and_empty_manifest_without_writes(sample_records):
    records = sample_records
    fulfillment = _source_sample(records, "source-cleanup-safety")
    from django.db.models.query import QuerySet

    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        external_id="SOURCE-CLEANUP-SAFETY",
    )
    manifest_digest = _import_manifest_digest(
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        task_external_ids=set(),
        sample_external_ids={"SOURCE-CLEANUP-SAFETY"},
    )
    batch = ImportBatch.objects.create(
        tenant=records["tenant"],
        source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        batch_key="source-cleanup-safety-batch",
        status=ImportBatch.Status.COMPLETED,
        manifest_digest=manifest_digest,
        created_by=records["executor"],
    )

    with pytest.raises(ValidationError, match="persisted completed import batch"):
        soft_delete_import_source(
            user=records["executor"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            batch=SimpleNamespace(pk=batch.pk),
            task_external_ids=set(),
            sample_external_ids={"SOURCE-CLEANUP-SAFETY"},
        )
    with pytest.raises(ValidationError, match="non-empty import manifest"):
        soft_delete_import_source(
            user=records["executor"],
            tenant=records["tenant"],
            source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
            batch=batch,
            task_external_ids=set(),
            sample_external_ids=set(),
        )
    fulfillment.refresh_from_db()
    assert fulfillment.is_deleted is False
    assert OperationLog.objects.filter(
        tenant=records["tenant"],
        action="feishu_import_source_soft_delete",
    ).count() == 0

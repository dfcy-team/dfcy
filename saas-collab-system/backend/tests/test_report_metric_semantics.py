import pytest
from django.core.exceptions import ValidationError

from apps.reports.models import SavedReportViewRevision
from apps.sales_management.views import _currency_metrics


def test_zero_denominator_is_undefined_but_true_zero_numerator_remains_zero():
    def metrics(gross, valid):
        row = dict(gross=gross, refunds=0, orders=valid, valid_orders=valid, cancelled_orders=0, units=0, currency="PHP")
        return {item["code"]: item["value"] for item in _currency_metrics(row)}
    assert metrics(0, 0)["average_order_value"] is None
    assert metrics(0, 0)["refund_rate"] is None
    assert metrics(100, 1)["refund_rate"] == "0"
    assert metrics(100, 1)["average_order_value"] == "100"


def test_saved_revisions_refuse_instance_and_queryset_mutation_before_database_access():
    with pytest.raises(ValidationError):
        SavedReportViewRevision(id=123).save()
    with pytest.raises(ValidationError):
        SavedReportViewRevision.objects.filter(pk=123).update(name="rewrite")
    with pytest.raises(ValidationError):
        SavedReportViewRevision.objects.filter(pk=123).delete()

"""Read-only checks for native supply payment approval readiness."""
import json

from .models import FeishuConnection, FeishuIdentity

UNSUPPORTED_INSTANCE_WIDGETS = {
    "text", "mutableGroup", "account", "serialNumber", "tripGroup",
    "apaascorehrOnboardingGroup", "apaascorehrRegularateGroup", "remedyGroupV2",
    "apaascorehrJobAdjustGroup", "apaascorehrOffboardingGroup",
}


def inspect_definition(definition, currencies):
    issues = []
    if definition.get("status") != "ACTIVE":
        issues.append("TEMPLATE_INACTIVE")
    form = definition.get("form", "[]")
    widgets = json.loads(form) if isinstance(form, str) else form
    if not isinstance(widgets, list):
        raise ValueError("Invalid approval form")
    unsupported = [widget.get("id") for widget in widgets
                   if widget.get("required") and widget.get("type") in UNSUPPORTED_INSTANCE_WIDGETS]
    if unsupported:
        issues.append("REQUIRED_WIDGET_UNSUPPORTED_BY_INSTANCE_API")
    account_numbers = [widget for widget in widgets if widget.get("name") == "收款账号"]
    if any(widget.get("type") != "input" for widget in account_numbers):
        issues.append("ACCOUNT_NUMBER_MUST_BE_TEXT")
    amounts = [widget for widget in widgets if widget.get("type") == "amount"]
    supported = set()
    if len(amounts) == 1:
        supported = set((amounts[0].get("option") or {}).get("currencyRange", []))
    else:
        issues.append("AMOUNT_WIDGET_AMBIGUOUS")
    if set(currencies) - supported:
        issues.append("TEMPLATE_CURRENCY_MISSING")
    nodes = definition.get("node_list", [])
    return {
        "issues": issues,
        "unsupported_required_widget_ids": unsupported,
        "currencies": sorted(supported),
        "widgets": [{"id": widget.get("id"), "name": widget.get("name"),
                     "type": widget.get("type"), "required": widget.get("required", False)}
                    for widget in widgets],
        "nodes": [{"id": node.get("node_id"), "name": node.get("name"),
                   "requires_submitted_approver": node.get("need_approver", False)} for node in nodes],
        "fixed_assignees_verified": False,
    }


def payment_preflight(*, tenant_id, approval_code, reviewer_id, currencies, client):
    from apps.workflows.models import PaymentApprovalFlow
    from apps.supply_chain.payment_request_models import SupplyPaymentRequest
    from apps.supply_chain.cost_models import PaymentRecord

    connection = FeishuConnection.objects.filter(tenant_id=tenant_id, enabled=True).first()
    issues = []
    flows = list(PaymentApprovalFlow.objects.filter(
        tenant_id=tenant_id, published=True, active=True).values("id", "version", "reviewer_id"))
    if not flows:
        issues.append("PAYMENT_FLOW_MISSING")
    if any(flow["reviewer_id"] != reviewer_id for flow in flows):
        issues.append("PAYMENT_FLOW_REVIEWER_MISMATCH")
    bound = FeishuIdentity.objects.filter(
        tenant_id=tenant_id, user_id=reviewer_id, status="active", user__is_active=True,
        user__tenant_id=tenant_id, user__user_type="internal").exclude(open_id="").exists()
    if not bound:
        issues.append("REVIEWER_IDENTITY_MISSING")
    callback_ready = bool(connection and connection.verification_token_ref)
    if not callback_ready:
        issues.append("CALLBACK_TOKEN_MISSING")
    fields = {field.name for field in SupplyPaymentRequest._meta.fields}
    payment_fields = {field.name for field in PaymentRecord._meta.fields}
    if set(currencies) - {"CNY"} and ("currency" not in fields or "currency" not in payment_fields):
        issues.append("PAYMENT_CURRENCY_STORAGE_MISSING")
    template = None
    if connection is None:
        issues.append("CONNECTION_MISSING")
    else:
        template = inspect_definition(client.get_definition(connection, approval_code), currencies)
        issues.extend(template["issues"])
    # These checks deliberately remain unresolved until the submit/回写 integration
    # exists and is exercised through the business entry points.
    issues.extend(["BUSINESS_SUBMISSION_UNVERIFIED", "CALLBACK_WRITEBACK_UNVERIFIED",
                   "TEMPLATE_SUBSCRIPTION_UNVERIFIED", "FIXED_ASSIGNEES_UNVERIFIED"])
    return {"status": "blocked", "tenant_id": tenant_id, "approval_code": approval_code,
            "requested_currencies": currencies, "flows": flows, "reviewer_bound": bound,
            "callback_token_configured": callback_ready,
            "callback_encryption_configured": bool(connection and connection.encrypt_key_ref),
            "template": template, "issues": sorted(set(issues))}

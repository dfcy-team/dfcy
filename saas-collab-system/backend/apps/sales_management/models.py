"""Sales-owned operating demand and compatibility imports for customer facts.

Customer sales facts, sync state, quality checks, and exports remain in their
canonical applications; operating demand is owned by sales management.
"""

from apps.commerce.models import (
    InventorySnapshot,
    RefundReturn,
    RefundReturnItem,
    SalesOrder,
    SalesOrderItem,
)
from apps.integrations.models import APIDataQualityCheck, SyncCursor, SyncJob, SyncRun
from apps.reports.models import ReportExportRequest
from .operating_models import OperatingOrder, OperatingOrderLine, OperatingSuggestion


SalesOrderLine = SalesOrderItem
SalesReturn = RefundReturn
DataQualityIssue = APIDataQualityCheck
SalesExportRequest = ReportExportRequest
SyncSource = SyncJob


__all__ = [
    "APIDataQualityCheck",
    "DataQualityIssue",
    "InventorySnapshot",
    "OperatingOrder",
    "OperatingOrderLine",
    "OperatingSuggestion",
    "RefundReturn",
    "RefundReturnItem",
    "ReportExportRequest",
    "SalesExportRequest",
    "SalesOrder",
    "SalesOrderItem",
    "SalesOrderLine",
    "SalesReturn",
    "SyncCursor",
    "SyncJob",
    "SyncRun",
    "SyncSource",
]

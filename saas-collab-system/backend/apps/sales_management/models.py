"""Compatibility imports for the sales-management API.

The application owns views and query policy only. Business facts, sync state,
quality checks, and exports remain in their canonical applications.
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


SalesOrderLine = SalesOrderItem
SalesReturn = RefundReturn
DataQualityIssue = APIDataQualityCheck
SalesExportRequest = ReportExportRequest
SyncSource = SyncJob


__all__ = [
    "APIDataQualityCheck",
    "DataQualityIssue",
    "InventorySnapshot",
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

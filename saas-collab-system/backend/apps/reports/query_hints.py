"""Narrow MySQL plan corrections for bounded sales/finance projections.

Production EXPLAIN selected the external-order uniqueness index on tenant alone
and scanned ~518k estimated rows for a month. The existing store/time index keeps
these reads bounded. No filter, join, permission or SQL parameter is changed.
"""
from contextlib import contextmanager

from django.db import connection


def _sales_time_index(execute, sql, params, many, context):
    table = "FROM `sales_order`"
    if sql.startswith("SELECT") and table in sql and "FORCE INDEX" not in sql:
        sql = sql.replace(table, table + " FORCE INDEX (`idx_sales_order_store_time`)", 1)
    return execute(sql, params, many, context)


@contextmanager
def bounded_fact_projection(config):
    filters = config.get("filters", {})
    wrappers = {"sales": _sales_time_index, "finance": _finance_date_index}
    if connection.vendor == "mysql" and config.get("dataset") in wrappers and filters.get("date_from") and filters.get("date_to"):
        with connection.execute_wrapper(wrappers[config["dataset"]]):
            yield
    else:
        yield


def _finance_date_index(execute, sql, params, many, context):
    # The production optimizer also preferred the finance uniqueness index on
    # tenant alone (~776k estimated rows) over the existing business-date index.
    table = "FROM `finance_platformfinancetransaction`"
    if sql.startswith("SELECT") and table in sql and "FORCE INDEX" not in sql:
        sql = sql.replace(table, table + " FORCE INDEX (`idx_fin_tx_tenant_date`)", 1)
    return execute(sql, params, many, context)

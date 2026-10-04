"""Same-shop Shopee order/catalogue reconciliation, never SKU-name guessing.

Only aggregate results and bounded identity pages leave the database. The
source watermark and keyset cursor make a pass finite even while orders arrive.
Historical order facts (including Shopee's model_id=0) are never rewritten.
"""
from django.db import connection
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.commerce.models import SalesOrder, SalesOrderItem
from apps.listings.models import PlatformProductDetail
from .models import PlatformIntegrationConfig, SyncJob, SyncRun


MODES = {"catalog_only", "catalog_and_order_missing", "order_missing_only"}
CURSOR_PREFIX = "order-gap:v1:"
SUMMARY_FIELDS = ["source_rows", "unique_pairs", "linked_pairs", "missing_pairs", "missing_product_ids",
                  "missing_variant_pairs", "conflict_pairs", "invalid_pairs", "zero_variant_pairs"]


def product_backfill_mode(config, resource_type, scope):
    supported = getattr(config, "platform", None) == "shopee" and resource_type == "platform_product"
    default = "catalog_and_order_missing" if supported else "catalog_only"
    value = scope.get("product_order_backfill", default)
    if value not in MODES or (not supported and value != "catalog_only"):
        raise ValidationError("订单缺失商品补采仅支持 Shopee 平台商品任务。")
    return value


def _subject(job):
    if (
        job.integration_config.platform != "shopee"
        or job.resource_type != "platform_product"
        or job.integration_config.environment not in {"production", "pilot"}
        or not job.store_authorization_id
    ):
        raise ValidationError("请使用绑定具体店铺的 Shopee 生产/试运行商品只读任务。")
    auth = job.store_authorization
    if (auth.tenant_id != job.tenant_id or auth.integration_config_id != job.integration_config_id
            or auth.platform != "shopee" or auth.store.tenant_id != job.tenant_id
            or auth.store.platform.platform_type != "shopee"):
        raise ValidationError("任务、授权和店铺的平台或租户范围不一致。")
    return job.tenant_id, auth.store.platform_id, auth.store_id


def _cohort(job, watermark=None):
    tenant, platform, store = _subject(job)
    quote = connection.ops.quote_name
    tables = [quote(model._meta.db_table) for model in
              (SalesOrder, SalesOrderItem, PlatformIntegrationConfig, SyncRun, SyncJob)]
    orders, items, configs, runs, jobs = tables
    # The production query follows the indexed order->item path, not a hash
    # join over every order item and every catalogue variant.
    join = "STRAIGHT_JOIN" if connection.vendor == "mysql" else "JOIN"
    order_index = "FORCE INDEX (idx_sales_order_store_time)" if connection.vendor == "mysql" else ""
    job_index = "FORCE INDEX (PRIMARY)" if connection.vendor == "mysql" else ""
    sql = f"""FROM {orders} o {order_index}
      {join} {configs} cfg ON cfg.id=o.authorization_id
      {join} {runs} sr ON sr.id=o.source_run_id
      {join} {jobs} sj {job_index} ON sj.id=sr.sync_job_id
      {join} {items} i ON i.sales_order_id=o.id
      WHERE o.tenant_id=%s AND o.platform_id=%s AND o.store_id=%s
        AND cfg.tenant_id=%s AND cfg.environment=%s AND cfg.platform='shopee'
        AND sj.tenant_id=%s AND sj.resource_type='sales_order'
        AND sr.tenant_id=o.tenant_id AND sj.integration_config_id=cfg.id"""
    params = [tenant, platform, store, tenant, job.integration_config.environment, tenant]
    if watermark is not None:
        sql += " AND i.id<=%s"
        params.append(watermark)
    return sql, params


def source_watermark(job):
    cohort, params = _cohort(job)
    with connection.cursor() as cursor:
        cursor.execute("SELECT MAX(i.id) " + cohort, params)
        return int(cursor.fetchone()[0] or 0)


def _classified(job, watermark):
    tenant, platform, store = _subject(job)
    cohort, params = _cohort(job, watermark)
    catalogue = connection.ops.quote_name(PlatformProductDetail._meta.db_table)
    index = "FORCE INDEX (uniq_platform_product_variant)" if connection.vendor == "mysql" else ""
    def numeric(column):
        if connection.vendor == "mysql":
            return f"{column} REGEXP '^[0-9]{{1,20}}$'"
        return f"(LENGTH({column}) BETWEEN 1 AND 20 AND {column} NOT GLOB '*[^0-9]*')"
    sql = f"""WITH sold AS (
      SELECT TRIM(i.platform_product_id) product_id, TRIM(i.platform_variant_id) variant_id,
        COUNT(*) item_rows {cohort}
      GROUP BY TRIM(i.platform_product_id), TRIM(i.platform_variant_id)
    ), products AS (
      SELECT DISTINCT platform_product_id FROM {catalogue}
      WHERE tenant_id=%s AND platform_id=%s AND store_id=%s
    ), keyed AS (
      SELECT sold.*, CASE WHEN variant_id IN ('','0') THEN product_id ELSE variant_id END canonical_variant_id
      FROM sold
    ), classified AS (
      SELECT k.*, CASE
        WHEN product_id IN ('','0') OR NOT ({numeric('k.product_id')})
          OR NOT ({numeric('k.canonical_variant_id')}) THEN 'invalid_identity'
        WHEN cv.id IS NOT NULL AND cv.platform_product_id=k.product_id THEN 'linked'
        WHEN cv.id IS NOT NULL THEN 'identity_conflict'
        WHEN cp.platform_product_id IS NULL THEN 'product_missing'
        ELSE 'variant_missing' END reason
      FROM keyed k LEFT JOIN products cp ON cp.platform_product_id=k.product_id
      LEFT JOIN {catalogue} cv {index}
        ON cv.tenant_id=%s AND cv.platform_id=%s AND cv.store_id=%s
          AND cv.platform_variant_id=k.canonical_variant_id
    ) """
    return sql, [*params, tenant, platform, store, tenant, platform, store]


def gap_candidates(job, watermark, last_product_id="", limit=50):
    # Fetch one lookahead identity only; do not materialize an entire shop's
    # missing-ID set or use offset pagination on a set that shrinks on upsert.
    limit = max(1, min(int(limit), 50))
    sql, params = _classified(job, watermark)
    sql += """SELECT DISTINCT product_id FROM classified
      WHERE reason IN ('product_missing','variant_missing') AND product_id>%s
      ORDER BY product_id LIMIT %s"""
    with connection.cursor() as cursor:
        cursor.execute(sql, [*params, last_product_id, limit + 1])
        ids = [row[0] for row in cursor.fetchall()]
    return ids[:limit], len(ids) > limit


def _summary_sql():
    return """SELECT COALESCE(SUM(item_rows),0) source_rows,COUNT(*) unique_pairs,
      COALESCE(SUM(CASE WHEN reason='linked' THEN 1 ELSE 0 END),0) linked_pairs,
      COALESCE(SUM(CASE WHEN reason!='linked' THEN 1 ELSE 0 END),0) missing_pairs,
      COUNT(DISTINCT CASE WHEN reason='product_missing' THEN product_id ELSE NULL END) missing_product_ids,
      COALESCE(SUM(CASE WHEN reason='variant_missing' THEN 1 ELSE 0 END),0) missing_variant_pairs,
      COALESCE(SUM(CASE WHEN reason='identity_conflict' THEN 1 ELSE 0 END),0) conflict_pairs,
      COALESCE(SUM(CASE WHEN reason='invalid_identity' THEN 1 ELSE 0 END),0) invalid_pairs,
      COALESCE(SUM(CASE WHEN variant_id IN ('','0') THEN 1 ELSE 0 END),0) zero_variant_pairs
      FROM classified"""


def _summary_result(values, watermark):
    return {**dict(zip(SUMMARY_FIELDS, [int(value or 0) for value in values])), "watermark": watermark}


def gap_summary(job, watermark):
    sql, params = _classified(job, watermark)
    with connection.cursor() as cursor:
        cursor.execute(sql + _summary_sql(), params)
        values = cursor.fetchone()
    return _summary_result(values, watermark)


def _report_sql(job, watermark):
    sql, params = _classified(job, watermark)
    # Reuse one materialized sold set for aggregate totals and bounded samples;
    # never transfer a shop's whole order/item or identity set to Python.
    sql += f""", stats AS ({_summary_sql()}), samples AS (
      SELECT product_id,variant_id,reason,item_rows FROM classified
      WHERE reason!='linked' ORDER BY reason,product_id,variant_id LIMIT 20
    ) SELECT stats.*,samples.product_id,samples.variant_id,samples.reason,samples.item_rows
      FROM stats LEFT JOIN samples ON 1=1 ORDER BY samples.reason,samples.product_id,samples.variant_id"""
    return sql, params


def gap_report(job):
    watermark = source_watermark(job)
    sql, params = _report_sql(job, watermark)
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    summary = _summary_result(rows[0][:len(SUMMARY_FIELDS)], watermark)
    samples = [dict(zip(["product_id", "variant_id", "reason", "item_rows"], row[len(SUMMARY_FIELDS):]))
               for row in rows if row[len(SUMMARY_FIELDS)] is not None]
    scope = job.sync_scope or {}
    policy_scope = {**scope, **(scope.get("query") or {})}
    return {
        "summary": summary, "samples": samples,
        "policy": product_backfill_mode(job.integration_config, job.resource_type, policy_scope),
        "checked_at": timezone.now().isoformat(),
        "notice": "只读检查当前店铺已落库订单与平台商品 ID 关系；未调用平台、未保存或执行任务。"
                  "model_id=0/空值按 item_id 单变体身份校验；不修改历史订单。冲突不自动覆盖，平台不返回的数据仍需核查。",
    }


def gap_cursor(watermark, last_product_id=""):
    return f"{CURSOR_PREFIX}{int(watermark)}:{last_product_id}"


def parse_gap_cursor(value):
    try:
        watermark, last = str(value)[len(CURSOR_PREFIX):].split(":", 1)
        if not str(value).startswith(CURSOR_PREFIX) or not watermark.isascii() or not watermark.isdecimal():
            raise ValueError()
        if len(watermark) > 19 or int(watermark) > 9223372036854775807:
            raise ValueError()
        if last and (not last.isascii() or not last.isdecimal() or len(last) > 20):
            raise ValueError()
        return int(watermark), last
    except (TypeError, ValueError):
        raise ValidationError("订单缺失商品补采游标无效，不能跳过未完成的进度。")

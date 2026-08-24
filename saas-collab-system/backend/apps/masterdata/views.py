import csv
import io
import re
import zipfile
from xml.etree import ElementTree

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.views import APIView

from apps.audit.services import write_operation_log
from apps.common.exceptions import StateConflict
from apps.common.responses import paginated_data, success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.ui_p2_scopes import filter_master_data, require_all_scope
from apps.suppliers.models import SupplierTask

from .models import PlatformMaster, StatusChoices, StoreMaster, SupplierMaster
from apps.accounts.models import CustomUser
from apps.products.models import ProductCategory
from .serializers import MODEL_BY_RESOURCE, SERIALIZER_BY_RESOURCE


def positive_int(value, default, maximum=100):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValidationError("Pagination values must be integers.")
    if parsed < 1 or parsed > maximum:
        raise ValidationError(f"Pagination value must be between 1 and {maximum}.")
    return parsed


def resource_contract(resource):
    if resource not in MODEL_BY_RESOURCE:
        raise NotFound("Unknown master-data resource.")
    return MODEL_BY_RESOURCE[resource], SERIALIZER_BY_RESOURCE[resource]


STORE_IMPORT_ALIASES = {
    "店铺档案编码": "code", "店铺编码": "code", "code": "code",
    "店铺名称": "name", "店铺档案名称": "name", "name": "name",
    "平台": "platform", "平台编码": "platform", "platform": "platform",
    "平台店铺名": "platform_store_name", "平台店铺名称": "platform_store_name",
    "platform_store_name": "platform_store_name",
    "国家代码": "country_code", "国家": "country_code", "country_code": "country_code",
    "币种": "currency", "currency": "currency", "时区": "timezone", "timezone": "timezone",
    "类目": "category", "分类": "category", "category": "category",
    "负责运营": "operator", "运营": "operator", "operator": "operator",
    "BD": "bd", "bd": "bd", "组长": "leader", "leader": "leader",
    "是否建联": "is_connected", "is_connected": "is_connected",
    "战斧客户端": "tactical_client", "tactical_client": "tactical_client",
    "状态": "status", "status": "status",
}


def _import_text(value):
    return "" if value is None else str(value).strip()


def _import_key(value):
    return re.sub(r"[\s_\-()（）]+", "", _import_text(value)).casefold()


def _xlsx_rows(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            shared = ["".join(node.itertext()) for node in root.findall("x:si", ns)]
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
        rel_map = {item.attrib["Id"]: item.attrib["Target"] for item in rels.findall("r:Relationship", rel_ns)}
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
        for sheet in workbook.findall("x:sheets/x:sheet", ns):
            target = rel_map.get(sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"), "")
            path = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
            if path not in archive.namelist():
                continue
            root = ElementTree.fromstring(archive.read(path)); rows = []
            for row in root.findall(".//x:sheetData/x:row", ns):
                cells = {}
                for cell in row.findall("x:c", ns):
                    ref = cell.attrib.get("r", "A1"); match = re.match(r"[A-Z]+", ref)
                    if not match: continue
                    value = cell.find("x:v", ns); text = "" if value is None else value.text or ""
                    if cell.attrib.get("t") == "s" and text.isdigit() and int(text) < len(shared): text = shared[int(text)]
                    inline = cell.find("x:is", ns)
                    if inline is not None: text = "".join(inline.itertext())
                    cells[match.group(0)] = text
                rows.append(cells)
            if rows:
                columns = sorted({c for row in rows for c in row}, key=lambda c: (len(c), c))
                yield sheet.attrib.get("name", ""), [[row.get(c, "") for c in columns] for row in rows]


def _store_import_rows(raw, filename=""):
    if filename.lower().endswith(".xlsx") or raw[:2] == b"PK":
        for sheet, rows in _xlsx_rows(raw):
            if rows: yield sheet, _map_store_rows(rows)
        return
    text = raw.decode("utf-8-sig", errors="replace")
    try: dialect = csv.Sniffer().sniff(text[:4096])
    except csv.Error: dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if rows: yield "", _map_store_rows(rows)


def _map_store_rows(rows):
    headers = rows[0]
    mapped = [next((value for key, value in STORE_IMPORT_ALIASES.items() if _import_key(key) == _import_key(header)), _import_key(header)) for header in headers]
    return [{mapped[i]: _import_text(row[i]) if i < len(row) else "" for i in range(len(mapped))} for row in rows[1:] if any(_import_text(v) for v in row)]


def import_stores(*, request, raw, filename="", dry_run=False):
    tenant = request.user.tenant; errors = []; plans = []; rows_seen = 0
    for sheet, rows in _store_import_rows(raw, filename):
        for line, row in enumerate(rows, start=2):
            rows_seen += 1
            try:
                code, name = _import_text(row.get("code")), _import_text(row.get("name"))
                platform_value = _import_text(row.get("platform"));
                if not code or not name or not platform_value: raise ValueError("店铺编码、店铺名称、平台为必填项")
                platform = PlatformMaster.objects.filter(tenant=tenant).filter(Q(code__iexact=platform_value) | Q(name__iexact=platform_value)).first()
                if not platform: raise ValueError(f"平台不存在: {platform_value}")
                category = None; category_value = _import_text(row.get("category"))
                if category_value:
                    category = ProductCategory.objects.filter(tenant=tenant, is_active=True).filter(Q(pk=category_value) if category_value.isdigit() else Q(code__iexact=category_value) | Q(name__iexact=category_value)).first()
                    if not category or category.level != ProductCategory.Level.L1: raise ValueError(f"一级类目不存在: {category_value}")
                refs = {}
                for field, label in (("operator", "负责运营"), ("bd", "BD"), ("leader", "组长")):
                    value = _import_text(row.get(field)); refs[field] = None
                    if value:
                        query = Q(username__iexact=value) | Q(full_name__iexact=value)
                        if value.isdigit(): query |= Q(pk=int(value))
                        refs[field] = CustomUser.objects.filter(tenant=tenant, is_active=True).filter(query).first()
                        if not refs[field]: raise ValueError(f"{label}用户不存在: {value}")
                connected = _import_text(row.get("is_connected")).casefold() in {"1", "true", "yes", "y", "是", "已建联", "active"}
                plans.append({"tenant": tenant, "platform": platform, "code": code, "name": name, "platform_store_name": _import_text(row.get("platform_store_name")), "category": category, **refs, "is_connected": connected, "tactical_client": _import_text(row.get("tactical_client")), "country_code": _import_text(row.get("country_code")).upper(), "currency": _import_text(row.get("currency")).upper(), "timezone": _import_text(row.get("timezone")) or "UTC", "status": _import_text(row.get("status")) or StatusChoices.ACTIVE})
            except (ValueError, TypeError, KeyError) as exc: errors.append({"row": line, "sheet": sheet, "message": str(exc)})
    created = updated = 0
    if not dry_run and not errors:
        with transaction.atomic():
            for values in plans:
                lookup = {"tenant": tenant, "code": values["code"]}; defaults = {k: v for k, v in values.items() if k not in lookup}
                _, made = StoreMaster.objects.update_or_create(defaults=defaults, **lookup); created += int(made); updated += int(not made)
    return {"dry_run": dry_run, "total": rows_seen, "valid": len(plans), "created": created, "updated": updated, "errors": errors}


class MasterDataCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "masterdata.view"
    write_permission_code = "masterdata.manage"

    def get(self, request, resource):
        model, serializer = resource_contract(resource)
        queryset = model.objects.filter(tenant=request.user.tenant)
        queryset = filter_master_data(request.user, queryset, self.read_permission_code, resource)
        if resource == "stores":
            queryset = queryset.select_related("platform", "category", "operator", "bd", "leader")
        search = request.query_params.get("search", "").strip()
        status = request.query_params.get("status", "").strip()
        if search:
            search_filter = Q(code__icontains=search) | Q(name__icontains=search)
            if resource == "stores":
                search_filter |= Q(platform_store_name__icontains=search) | Q(category__name__icontains=search)
            if resource == "sites":
                search_filter |= Q(country_code__icontains=search) | Q(currency__icontains=search) | Q(timezone__icontains=search)
            queryset = queryset.filter(search_filter)
        if status:
            queryset = queryset.filter(status=status)
        page = positive_int(request.query_params.get("page", 1), 1)
        page_size = positive_int(request.query_params.get("page_size", 20), 20)
        return success_response(paginated_data(request, queryset, serializer, page=page, page_size=page_size))

    def post(self, request, resource):
        require_all_scope(request.user, self.write_permission_code)
        if resource == "stores" and (request.FILES.get("file") or request.data.get("csv_text") is not None):
            upload = request.FILES.get("file")
            raw = upload.read() if upload else str(request.data.get("csv_text", "")).encode("utf-8-sig")
            if not raw:
                raise ValidationError({"file": "店铺档案导入文件不能为空。"})
            result = import_stores(
                request=request,
                raw=raw,
                filename=getattr(upload, "name", ""),
                dry_run=str(request.data.get("dry_run", "")).lower() in {"1", "true", "yes", "on"},
            )
            return success_response(result)
        _, serializer_class = resource_contract(resource)
        serializer = serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(tenant=request.user.tenant)
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="masterdata",
            action="create",
            object_type=resource,
            object_id=instance.pk,
            after_data={"code": instance.code, "status": instance.status},
        )
        return success_response(serializer_class(instance, context={"request": request}).data, status=201)


class MasterDataDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "masterdata.view"
    write_permission_code = "masterdata.manage"

    def get_object(self, request, resource, pk):
        model, _ = resource_contract(resource)
        queryset = model.objects.filter(tenant=request.user.tenant)
        permission_code = self.read_permission_code if request.method == "GET" else self.write_permission_code
        return get_object_or_404(filter_master_data(request.user, queryset, permission_code, resource), pk=pk)

    def get(self, request, resource, pk):
        instance = self.get_object(request, resource, pk)
        _, serializer_class = resource_contract(resource)
        return success_response(serializer_class(instance, context={"request": request}).data)

    def patch(self, request, resource, pk):
        instance = self.get_object(request, resource, pk)
        before = {"code": instance.code, "status": instance.status}
        _, serializer_class = resource_contract(resource)
        serializer = serializer_class(
            instance, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="masterdata",
            action="update",
            object_type=resource,
            object_id=instance.pk,
            before_data=before,
            after_data={"code": instance.code, "status": instance.status},
        )
        return success_response(serializer.data)


class MasterDataStatusView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "masterdata.view"
    write_permission_code = "masterdata.manage"

    def post(self, request, resource, pk):
        model, serializer_class = resource_contract(resource)
        queryset = model.objects.filter(tenant=request.user.tenant)
        instance = get_object_or_404(
            filter_master_data(request.user, queryset, self.write_permission_code, resource),
            pk=pk,
        )
        status = request.data.get("status")
        if status not in StatusChoices.values:
            raise ValidationError({"status": "Status must be active or inactive."})
        if status == StatusChoices.INACTIVE and isinstance(instance, PlatformMaster) and instance.stores.filter(
            status=StatusChoices.ACTIVE
        ).exists():
            raise StateConflict("An active store still references this platform.")
        if status == StatusChoices.INACTIVE and isinstance(instance, SupplierMaster) and SupplierTask.objects.filter(
            tenant=request.user.tenant,
            supplier_id=instance.pk,
            status__in=["pending", "in_progress", "partial"],
        ).exists():
            raise StateConflict("An active supplier task still references this supplier.")
        before = instance.status
        instance.status = status
        instance.save(update_fields=["status", "updated_at"])
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="masterdata",
            action="status_change",
            object_type=resource,
            object_id=instance.pk,
            before_data={"status": before},
            after_data={"status": status},
        )
        return success_response(serializer_class(instance, context={"request": request}).data)

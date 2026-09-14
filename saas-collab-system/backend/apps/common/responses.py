from django.core.paginator import Paginator
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from .error_codes import ErrorCode


def success_response(data=None, message="success", code=ErrorCode.OK, status=200):
    return Response(
        {
            "success": True,
            "code": code,
            "message": message,
            "data": data if data is not None else {},
        },
        status=status,
    )


def error_response(code, message, data=None, status=400):
    return Response(
        {
            "success": False,
            "code": code,
            "message": message,
            "data": data,
        },
        status=status,
    )


def paginated_data(
    request,
    queryset,
    serializer_class,
    *,
    page,
    page_size,
    serializer_context=None,
    include_count=True,
    prepare_page=None,
):
    """Return the Phase 3 collection envelope payload without legacy wrappers."""
    def page_url(target_page):
        if target_page is None:
            return None
        params = request.query_params.copy()
        params["page"] = target_page
        params["page_size"] = page_size
        return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")

    if include_count:
        paginator = Paginator(queryset, page_size)
        if page > paginator.num_pages:
            raise NotFound("Requested page does not exist.")
        page_obj = paginator.page(page)
        rows = list(page_obj.object_list)
        count = paginator.count
        has_next = page_obj.has_next()
        has_previous = page_obj.has_previous()
    else:
        offset = (page - 1) * page_size
        rows = list(queryset[offset : offset + page_size + 1])
        has_next = len(rows) > page_size
        rows = rows[:page_size]
        if page > 1 and not rows:
            raise NotFound("Requested page does not exist.")
        count = None
        has_previous = page > 1

    if prepare_page is not None:
        prepare_page(rows)

    return {
        "count": count,
        "count_exact": include_count,
        "has_next": has_next,
        "next": page_url(page + 1) if has_next else None,
        "previous": page_url(page - 1) if has_previous else None,
        "results": serializer_class(
            rows,
            many=True,
            context=serializer_context or {},
        ).data,
    }

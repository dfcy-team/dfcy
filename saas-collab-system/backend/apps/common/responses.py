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


def paginated_data(request, queryset, serializer_class, *, page, page_size):
    """Return the Phase 3 collection envelope payload without legacy wrappers."""
    paginator = Paginator(queryset, page_size)
    if page > paginator.num_pages:
        raise NotFound("Requested page does not exist.")
    page_obj = paginator.page(page)

    def page_url(target_page):
        if target_page is None:
            return None
        params = request.query_params.copy()
        params["page"] = target_page
        params["page_size"] = page_size
        return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")

    return {
        "count": paginator.count,
        "next": page_url(page_obj.next_page_number()) if page_obj.has_next() else None,
        "previous": page_url(page_obj.previous_page_number()) if page_obj.has_previous() else None,
        "results": serializer_class(page_obj.object_list, many=True).data,
    }

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

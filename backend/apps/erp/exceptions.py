from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


def erp_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        return response
    if isinstance(exc, IntegrityError):
        return Response(
            {
                "code": "data_conflict",
                "detail": "数据与现有记录冲突，请检查单号、SKU、条码或幂等键是否重复。",
            },
            status=status.HTTP_409_CONFLICT,
        )
    return None

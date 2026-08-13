import logging
import uuid

from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


logger = logging.getLogger(__name__)


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
    diagnostic_id = uuid.uuid4().hex[:12]
    request = context.get("request")
    logger.exception(
        "Unhandled ERP API error diagnostic_id=%s method=%s path=%s view=%s",
        diagnostic_id,
        getattr(request, "method", ""),
        getattr(request, "path", ""),
        context.get("view").__class__.__name__ if context.get("view") else "",
    )
    return Response(
        {
            "code": "internal_error",
            "detail": "服务器处理失败，请提供诊断编号给技术人员排查。",
            "diagnostic_id": diagnostic_id,
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )

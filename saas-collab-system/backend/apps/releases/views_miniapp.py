from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.accounts.miniapp_permissions import IsMiniAppToken
from apps.common.responses import success_response

from .models import ReleaseContract
from .permissions import IsReleaseViewer, filter_release_scope
from .serializers import MiniAppReleaseContractDetailSerializer, ReleaseContractSummarySerializer


def _visible_contracts(user):
    return filter_release_scope(
        user,
        "release.contract.view",
        ReleaseContract.objects.select_related("created_by")
        .prefetch_related("gate_results", "approvals"),
    )


class MiniAppReleaseWorkbenchView(APIView):
    permission_classes = [IsAuthenticated, IsMiniAppToken, IsReleaseViewer]

    def get(self, request):
        queryset = _visible_contracts(request.user)
        status_counts = {
            row["status"]: row["count"]
            for row in queryset.values("status").annotate(count=Count("id"))
        }
        recent = queryset[:10]
        return success_response(
            {
                "read_only": True,
                "total": queryset.count(),
                "status_counts": status_counts,
                "recent": ReleaseContractSummarySerializer(recent, many=True).data,
            }
        )


class MiniAppReleaseContractDetailView(APIView):
    permission_classes = [IsAuthenticated, IsMiniAppToken, IsReleaseViewer]

    def get(self, request, pk):
        contract = get_object_or_404(_visible_contracts(request.user), pk=pk)
        return success_response(
            {
                "read_only": True,
                "contract": MiniAppReleaseContractDetailSerializer(contract).data,
            }
        )

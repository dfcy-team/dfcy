from django.core.paginator import Paginator
from rest_framework import serializers
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.permissions.services import check_user_permission
from .models import InfluencerRequirement


class RequirementInput(serializers.Serializer):
    title = serializers.CharField(max_length=120, label="需求标题")
    description = serializers.CharField(max_length=3000, label="需求说明")


class RequirementFeedbackPermission(BasePermission):
    permission_codes = ("influencers.requirements.submit", "influencers.requirements.review")
    message = "无权访问达人模块需求反馈。"

    def has_permission(self, request, view):
        user = request.user
        return user.user_type == "internal" and any(
            check_user_permission(user, code) for code in self.permission_codes
        )


class InfluencerRequirementView(APIView):
    permission_classes = [IsAuthenticated, RequirementFeedbackPermission]

    def get(self, request):
        can_review = check_user_permission(request.user, "influencers.requirements.review")
        rows = InfluencerRequirement.objects.filter(tenant_id=request.user.tenant_id)
        if not can_review:
            rows = rows.filter(author_id=request.user.pk)
        paginator = Paginator(rows.values("id", "title", "description", "created_at", "author__username"), 20)
        page = paginator.get_page(request.query_params.get("page", 1))
        return success_response({"results": list(page), "count": paginator.count, "page": page.number,
                                 "can_review": can_review})

    def post(self, request):
        form = RequirementInput(data=request.data)
        form.is_valid(raise_exception=True)
        row = InfluencerRequirement.objects.create(
            tenant_id=request.user.tenant_id, author=request.user, **form.validated_data,
        )
        return success_response({"id": row.pk}, status=201)

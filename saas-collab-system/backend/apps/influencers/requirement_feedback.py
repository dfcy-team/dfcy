from io import BytesIO
import warnings

from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from PIL import Image, UnidentifiedImageError
from rest_framework import serializers
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.permissions.services import check_user_permission
from .models import InfluencerRequirement, InfluencerRequirementImage

MAX_IMAGE_BYTES = 2 * 1024 * 1024


def scoped_requirements(user):
    rows = InfluencerRequirement.objects.filter(tenant_id=user.tenant_id)
    if not check_user_permission(user, "influencers.requirements.review"):
        rows = rows.filter(author_id=user.pk)
    return rows


def image_content(upload):
    if upload.size > MAX_IMAGE_BYTES:
        raise serializers.ValidationError("每张图片不能超过 2 MB。")
    content = upload.read(MAX_IMAGE_BYTES + 1)
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise serializers.ValidationError("图片为空或超过 2 MB。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 20_000_000:
                    raise ValueError("unsupported image")
                image.load()
                # Re-encode to remove EXIF and trailing non-image payloads.
                output = BytesIO()
                image.convert("RGB").save(output, format="JPEG", quality=90)
                result = output.getvalue()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise serializers.ValidationError("请上传有效的 JPG、PNG 或 WebP 图片，像素不能超过 2000 万。")
    if len(result) > MAX_IMAGE_BYTES:
        raise serializers.ValidationError("图片处理后超过 2 MB，请缩小图片后上传。")
    return result


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
        rows = scoped_requirements(request.user)
        paginator = Paginator(rows.values("id", "title", "description", "created_at", "author__username"), 20)
        page = paginator.get_page(request.query_params.get("page", 1))
        results = list(page)
        images = InfluencerRequirementImage.objects.filter(requirement_id__in=[row["id"] for row in results]).values("id", "requirement_id")
        grouped = {}
        for image in images:
            grouped.setdefault(image["requirement_id"], []).append(image["id"])
        for row in results:
            row["image_ids"] = grouped.get(row["id"], [])
        return success_response({"results": results, "count": paginator.count, "page": page.number,
                                 "can_review": can_review})

    def post(self, request):
        form = RequirementInput(data=request.data)
        form.is_valid(raise_exception=True)
        uploads = request.FILES.getlist("images")
        if len(uploads) > 3:
            raise serializers.ValidationError("最多上传 3 张图片。")
        contents = [image_content(upload) for upload in uploads]
        with transaction.atomic():
            row = InfluencerRequirement.objects.create(
                tenant_id=request.user.tenant_id, author=request.user, **form.validated_data,
            )
            InfluencerRequirementImage.objects.bulk_create([
                InfluencerRequirementImage(requirement=row, content=content) for content in contents
            ])
        return success_response({"id": row.pk}, status=201)


class InfluencerRequirementImageView(APIView):
    permission_classes = [IsAuthenticated, RequirementFeedbackPermission]

    def get(self, request, pk, image_id):
        requirement = get_object_or_404(scoped_requirements(request.user), pk=pk)
        image = get_object_or_404(InfluencerRequirementImage, pk=image_id, requirement=requirement)
        response = HttpResponse(bytes(image.content), content_type="image/jpeg")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

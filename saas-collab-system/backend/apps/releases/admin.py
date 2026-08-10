from django.contrib import admin

from .models import (
    ReleaseApproval,
    ReleaseArtifact,
    ReleaseAuditEvent,
    ReleaseContract,
    ReleaseGateResult,
)


admin.site.register(
    (
        ReleaseContract,
        ReleaseArtifact,
        ReleaseGateResult,
        ReleaseApproval,
        ReleaseAuditEvent,
    )
)

"""Pure, fail-closed admission plan for migrating external collection timers.

This module does not create jobs, enable capabilities, or stop services.
Callers must supply current, tenant-scoped evidence from the business layer.
"""
from collections import defaultdict


RESOURCES = {"creator_profile": "CREATOR", "video_metrics": "VIDEO"}


def plan_cutover(*, tenant_id, authorizations, capabilities, jobs, timers):
    if type(tenant_id) is not int or tenant_id <= 0:
        raise ValueError("invalid_tenant")
    auths = defaultdict(list)
    for auth in authorizations:
        if (auth["tenant_id"] == tenant_id and auth["platform"] == "tiktok"
                and auth["status"] == "active"):
            auths[auth["store_id"]].append(auth)
    allowed = {
        (cap["authorization_id"], cap["code"])
        for cap in capabilities
        if cap["tenant_id"] == tenant_id and cap["read_enabled"] is True
        and cap["status"] == "active" and cap["write_enabled"] is False
    }
    indexed_jobs = defaultdict(list)
    for job in jobs:
        if job["tenant_id"] == tenant_id:
            indexed_jobs[(job["authorization_id"], job["resource_type"])].append(job)
    rows = []
    by_subject = {}
    for store_id, candidates in sorted(auths.items()):
        for resource, capability in RESOURCES.items():
            row = {"store_id": store_id, "resource_type": resource,
                   "authorization_id": None, "job_id": None,
                   "action": "blocked", "reason": "ambiguous_authorization",
                   "verified_system_owner": False}
            if len(candidates) == 1:
                auth = candidates[0]
                row["authorization_id"] = auth["id"]
                matches = indexed_jobs[(auth["id"], resource)]
                if (auth["id"], capability) not in allowed:
                    row["reason"] = "capability_not_enabled"
                elif not auth.get("preflight_passed", False):
                    row["reason"] = "preflight_not_passed"
                elif len(matches) > 1:
                    row["reason"] = "duplicate_jobs"
                elif matches and matches[0]["integration_config_id"] != auth["integration_config_id"]:
                    row["reason"] = "job_configuration_mismatch"
                elif matches:
                    job = matches[0]
                    row.update(action="reuse", reason="", job_id=job["id"])
                    row["verified_system_owner"] = bool(
                        job.get("scheduler_ready") is True
                        and job.get("verified_live_run") is True
                        and job.get("cutover_fence_ready") is True
                    )
                else:
                    row.update(action="create_disabled", reason="")
            rows.append(row)
            by_subject[(store_id, resource)] = row
    timer_rows = []
    for timer in timers:
        if timer["tenant_id"] != tenant_id:
            continue
        subjects = set(tuple(subject) for subject in timer["subjects"])
        unresolved = sorted(subject for subject in subjects
                            if not by_subject.get(subject, {}).get("verified_system_owner"))
        safe = bool(subjects) and not unresolved and timer.get("active_run") is False
        timer_rows.append({"name": timer["name"], "safe_to_disable": safe,
                           "unresolved_subjects": unresolved,
                           "reason": "" if safe else "coverage_or_inflight_not_verified"})
    return {"tenant_id": tenant_id, "jobs": rows, "timers": timer_rows,
            "mutations_performed": False}

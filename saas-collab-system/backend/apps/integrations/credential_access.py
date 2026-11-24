"""Shared marketplace credential reads; renewal remains owned by its existing queue."""
from datetime import timedelta
import logging
import os
from pathlib import Path

from celery.exceptions import WorkerShutdown
from celery.signals import beat_init, worker_init
from django.conf import settings
from django.core.checks import Error, register
from django.db import connections
from django.utils import timezone

from .custody import CustodyError, CustodyReferenceNotFound, HttpCustodyBackend, get_custody_backend
from .production_settings import runtime_snapshot


MESSAGES = {
    "RUNTIME_CONFIG_INVALID": "运行配置不兼容，等待部署修复；未提交平台请求",
    "CUSTODY_NOT_CONFIGURED": "凭据托管配置不可用，等待修复；未提交平台请求",
    "CUSTODY_UNAVAILABLE": "凭据托管暂不可用，等待恢复；未提交平台请求",
    "CREDENTIAL_REFERENCE_MISSING": "托管凭据引用不存在或为空，请核对授权；未提交平台请求",
    "TOKEN_REFRESH_REQUIRED": "等待既有凭据续期流程完成；未提交平台请求",
}


class CredentialAccessError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])


def require_token_validity(authorization, *, minimum_validity_seconds=0, now=None):
    expires_at = authorization.expires_at
    if not expires_at or expires_at <= (now or timezone.now()) + timedelta(seconds=minimum_validity_seconds):
        raise CredentialAccessError("TOKEN_REFRESH_REQUIRED")


def checked_custody_backend():
    snapshot = runtime_snapshot()
    if not snapshot["valid"]:
        raise CredentialAccessError("RUNTIME_CONFIG_INVALID")
    backend = snapshot["config"]["custody"]["backend"]
    if backend == "refuse" or (not settings.DEBUG and backend != "http"):
        raise CredentialAccessError("CUSTODY_NOT_CONFIGURED")
    ca_path = snapshot["config"]["custody"].get("ca_file_path")
    if ca_path and (not Path(ca_path).is_file() or not os.access(ca_path, os.R_OK)):
        raise CredentialAccessError("CUSTODY_NOT_CONFIGURED")
    try:
        custody = get_custody_backend()
    except CustodyError:
        raise CredentialAccessError("CUSTODY_NOT_CONFIGURED") from None
    if not settings.DEBUG and not isinstance(custody, HttpCustodyBackend):
        raise CredentialAccessError("CUSTODY_NOT_CONFIGURED")
    return custody


def retrieve_marketplace_credentials(config, authorization, *, custody=None,
                                     minimum_validity_seconds=0, now=None):
    require_token_validity(authorization, minimum_validity_seconds=minimum_validity_seconds, now=now)
    custody = custody if custody is not None else checked_custody_backend()
    try:
        secret = custody.retrieve_secret(config.credential_id or config.platform_config.get("app_secret_reference"))
        token = custody.retrieve_access_token(authorization.token_id)
    except CustodyReferenceNotFound:
        raise CredentialAccessError("CREDENTIAL_REFERENCE_MISSING") from None
    except CustodyError:
        raise CredentialAccessError("CUSTODY_UNAVAILABLE") from None
    if not isinstance(secret, str) or not secret or not isinstance(token, str) or not token:
        raise CredentialAccessError("CREDENTIAL_REFERENCE_MISSING")
    return secret, token


def _live_credentials_required():
    return not settings.DEBUG and (getattr(settings, "FLASH_SALES_WORKERS_ENABLED", False)
                                   or getattr(settings, "LIVE_READONLY_SYNC_ENABLED", False))


@register("integration_credentials", deploy=True)
def check_integration_credentials(app_configs=None, **kwargs):
    if _live_credentials_required():
        try:
            checked_custody_backend()
        except CredentialAccessError as exc:
            return [Error(str(exc), id="integrations.E001")]
    return []


def check_worker_credentials(sender=None, **kwargs):
    if not _live_credentials_required():
        return
    logger = logging.getLogger(__name__)
    try:
        checked_custody_backend()
    except CredentialAccessError as exc:
        logger.critical("Integration credential readiness failed (%s).", exc.code)
        raise WorkerShutdown(1) from None
    finally:
        connections.close_all()
    logger.info("Integration credential readiness passed.")


worker_init.connect(check_worker_credentials, weak=False, dispatch_uid="integration-credential-readiness")
beat_init.connect(check_worker_credentials, weak=False, dispatch_uid="integration-credential-readiness")

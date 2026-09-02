"""Production-safe OpenAI Responses API execution for governance assistants.

This module deliberately uses the standard library HTTP client so the worker
does not need to persist an SDK object or credentials.  The only credential
read is from the configured file (preferred) or the compatibility environment
variable, and neither is ever included in a model, exception, or log record.
"""

import json
import hashlib
import os
import re
import ssl
import stat
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import write_operation_log

from .models import AssistantDefinition, AssistantEvaluationJob


MAX_SECRET_FILE_BYTES = 8192
MAX_SECRET_LENGTH = 4096
MAX_RESULT_CHARS = 12000
MAX_FINDING_CHARS = 500
SAFE_SECRET_FILE_MODES = frozenset({0o400, 0o440, 0o600, 0o640})
RETRYABLE_HTTP_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})


class EvaluationDependencyError(Exception):
    """A local configuration or dependency failure safe to expose by code."""

    def __init__(self, code, message, *, retryable=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _setting(name, default=None):
    return getattr(settings, name, default)


def _validate_key(value):
    if not isinstance(value, str):
        raise EvaluationDependencyError("OPENAI_KEY_INVALID", "OpenAI credential is invalid.")
    value = value.strip()
    if not value or len(value) > MAX_SECRET_LENGTH or not value.startswith("sk-"):
        raise EvaluationDependencyError("OPENAI_KEY_INVALID", "OpenAI credential is invalid.")
    return value


def _read_secret_file(path, *, label):
    if not path:
        raise EvaluationDependencyError(f"{label}_FILE_MISSING", f"{label} credential file is not configured.")
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise EvaluationDependencyError(f"{label}_FILE_UNAVAILABLE", f"{label} credential file is unavailable.") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise EvaluationDependencyError(f"{label}_FILE_INVALID", f"{label} credential file must be a regular file.")
    # Accept exactly the operator-safe POSIX modes requested by the deployment
    # contract.  No group/world write bit is ever accepted.
    mode = stat.S_IMODE(metadata.st_mode)
    if mode not in SAFE_SECRET_FILE_MODES:
        raise EvaluationDependencyError(f"{label}_FILE_PERMISSIONS", f"{label} credential file permissions are unsafe.")
    if metadata.st_size <= 0 or metadata.st_size > MAX_SECRET_FILE_BYTES:
        raise EvaluationDependencyError(f"{label}_FILE_SIZE", f"{label} credential file size is invalid.")
    try:
        with open(path, "r", encoding="utf-8", errors="strict") as handle:
            value = handle.read(MAX_SECRET_FILE_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        raise EvaluationDependencyError(f"{label}_FILE_UNAVAILABLE", f"{label} credential file is unavailable.") from exc
    if len(value) > MAX_SECRET_FILE_BYTES:
        raise EvaluationDependencyError(f"{label}_FILE_SIZE", f"{label} credential file size is invalid.")
    return value.strip()


def load_openai_api_key():
    """Load the OpenAI key without ever exposing it to callers except memory."""

    key_file = str(_setting("OPENAI_API_KEY_FILE", "") or "").strip()
    if key_file:
        return _validate_key(_read_secret_file(key_file, label="OPENAI_KEY"))
    # Compatibility fallback.  A file setting always wins and fails closed if
    # it is malformed; this prevents accidental fallback to a stale env key.
    value = str(_setting("OPENAI_API_KEY", "") or "").strip()
    if not value:
        raise EvaluationDependencyError("OPENAI_KEY_MISSING", "OpenAI credential is not configured.")
    return _validate_key(value)


def _base_url():
    base_url = str(_setting("OPENAI_API_BASE_URL", "https://api.openai.com/v1") or "").strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" and not bool(_setting("OPENAI_ALLOW_INSECURE_FOR_TESTS", False)):
        raise EvaluationDependencyError("OPENAI_ENDPOINT_INSECURE", "OpenAI endpoint must use HTTPS.")
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise EvaluationDependencyError("OPENAI_ENDPOINT_INVALID", "OpenAI endpoint is invalid.")
    if parsed.query or parsed.fragment:
        raise EvaluationDependencyError("OPENAI_ENDPOINT_INVALID", "OpenAI endpoint is invalid.")
    return base_url


def openai_dependency_status():
    """Return non-sensitive readiness information for API responses."""

    try:
        load_openai_api_key()
    except EvaluationDependencyError as exc:
        if exc.code in {"OPENAI_KEY_MISSING", "OPENAI_KEY_FILE_MISSING", "OPENAI_KEY_FILE_UNAVAILABLE"} and not _setting("OPENAI_API_KEY", ""):
            return {"status": "blocked", "code": exc.code}
        return {"status": "degraded", "code": exc.code}
    try:
        _base_url()
        model = str(_setting("OPENAI_MODEL", "") or "").strip()
        if not model or len(model) > 120:
            raise EvaluationDependencyError("OPENAI_MODEL_INVALID", "OpenAI model is invalid.")
    except EvaluationDependencyError as exc:
        return {"status": "degraded", "code": exc.code}
    return {"status": "connected", "code": "OK"}


def _sanitized_usage(value):
    """Keep numeric token usage only; provider response metadata is not stored."""

    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        raw = value.get(key)
        if isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= 10_000_000:
            result[key] = raw
    return result


def _output_text(payload):
    if not isinstance(payload, dict):
        raise EvaluationDependencyError("OPENAI_RESPONSE_INVALID", "OpenAI returned an invalid response.")
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct[:MAX_RESULT_CHARS]
    fragments = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if content.get("type") in {"output_text", "text"} and isinstance(text, str):
                fragments.append(text)
    value = "\n".join(fragments).strip()
    if not value:
        raise EvaluationDependencyError("OPENAI_EMPTY_OUTPUT", "OpenAI returned no evaluation text.")
    return value[:MAX_RESULT_CHARS]


def _structured_evaluation(output, expected_output):
    """Normalize the provider's bounded evaluation envelope.

    A model can occasionally ignore the JSON-only instruction. Keep that
    response as the assistant output, but make the evaluation explicitly
    failed instead of dropping it or treating an unstructured answer as a
    passing test. No provider response is written to audit logs.
    """

    text = str(output or "").strip()[:MAX_RESULT_CHARS]
    candidate = text
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE | re.DOTALL).strip()
    parsed = None
    try:
        value = json.loads(candidate)
        if isinstance(value, dict):
            parsed = value
    except (TypeError, json.JSONDecodeError):
        parsed = None

    if parsed is None:
        return {
            "assistant_output": text,
            "passed": False,
            "score": 0,
            "findings": ["Provider returned an unstructured evaluation envelope."],
            "result_summary": "The assistant response could not be evaluated against the expected output.",
        }

    assistant_output = parsed.get("assistant_output", parsed.get("output", ""))
    if not isinstance(assistant_output, str):
        assistant_output = json.dumps(assistant_output, ensure_ascii=False, sort_keys=True)
    assistant_output = assistant_output.strip()[:MAX_RESULT_CHARS]
    passed = parsed.get("passed", parsed.get("pass"))
    if not isinstance(passed, bool):
        passed = None
    score = parsed.get("score")
    if isinstance(score, bool):
        score = None
    if isinstance(score, (int, float)) and 0 <= score <= 100:
        score = round(float(score), 2)
    else:
        score = 100.0 if passed is True else 0.0 if passed is False else None
    findings = parsed.get("findings", [])
    if isinstance(findings, str):
        findings = [findings]
    if not isinstance(findings, list):
        findings = []
    clean_findings = []
    for finding in findings[:20]:
        if isinstance(finding, str) and finding.strip() and not any(ord(char) < 32 for char in finding):
            clean_findings.append(finding.strip()[:MAX_FINDING_CHARS])
    summary = parsed.get("summary", parsed.get("result_summary", ""))
    if not isinstance(summary, str):
        summary = ""
    summary = summary.strip()[:1000]
    if passed is None:
        clean_findings.append("Provider did not return a boolean pass result.")
        passed = False
    if not summary:
        summary = "Assistant evaluation passed." if passed else "Assistant evaluation failed."
    # The expected output is intentionally used in the prompt and never
    # echoed into audit metadata; retain this reference to make the contract
    # explicit for callers and prevent an accidental unused-argument change.
    _ = expected_output
    return {
        "assistant_output": assistant_output,
        "passed": passed,
        "score": score,
        "findings": clean_findings,
        "result_summary": summary,
    }


def build_evaluation_prompt(assistant, *, scenario, test_input, expected_output, reason):
    """Build a bounded, tool-free prompt for a real synthetic assistant test."""

    metadata = {
        "assistant_code": assistant.code,
        "assistant_name": assistant.name,
        "assistant_version": assistant.version,
        "data_class": assistant.data_class,
        "declared_outputs": assistant.output_types or [],
        "allowed_tools": assistant.allowed_tools or [],
        "limitations": assistant.limitations or [],
        "scenario": scenario,
        "test_input": test_input,
        "expected_output": expected_output,
        "request_reason": reason,
    }
    prompt = (
        "Execute one synthetic public-demo test for the governed assistant below. "
        "Use the test_input as the user message and follow the assistant's declared "
        "outputs and limitations. Do not call tools, access credentials, access "
        "business data, or propose business writes. Compare the generated answer "
        "with expected_output as an acceptance criterion. Return ONLY a JSON object "
        "with these fields: assistant_output (string), passed (boolean), score "
        "(number 0..100), findings (array of concise strings), summary (string).\n\n"
        + json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    maximum = int(_setting("OPENAI_MAX_INPUT_CHARS", 12000) or 12000)
    return prompt[: max(256, min(maximum, 50000))]


def safety_identifier_for(assistant, *, scenario, test_input, expected_output):
    """Return a non-reversible provider safety identifier with no PII."""

    input_digest = hashlib.sha256(str(test_input).encode("utf-8")).hexdigest()
    expected_digest = hashlib.sha256(str(expected_output).encode("utf-8")).hexdigest()
    raw = f"governance-assistant:{assistant.pk}:{assistant.version}:{scenario}:{input_digest}:{expected_digest}"
    # Responses API safety_identifier is capped at 64 characters. Keep the
    # stable namespace prefix while truncating only the one-way digest; the
    # identifier remains non-reversible and contains no source values.
    return f"gov_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:60]}"


class OpenAIResponsesClient:
    """Small bounded client for POST /v1/responses."""

    def evaluate(self, assistant, *, scenario, test_input, expected_output, reason):
        api_key = load_openai_api_key()
        url = f"{_base_url()}/responses"
        model = str(_setting("OPENAI_MODEL", "") or "").strip()
        if not model or len(model) > 120:
            raise EvaluationDependencyError("OPENAI_MODEL_INVALID", "OpenAI model is invalid.")
        prompt = build_evaluation_prompt(
            assistant,
            scenario=scenario,
            test_input=test_input,
            expected_output=expected_output,
            reason=reason,
        )
        body = json.dumps(
            {
                "model": model,
                "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                "tools": [],
                "store": False,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "assistant_evaluation",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "assistant_output": {"type": "string"},
                                "passed": {"type": "boolean"},
                                "score": {"type": "number", "minimum": 0, "maximum": 100},
                                "findings": {"type": "array", "items": {"type": "string"}},
                                "summary": {"type": "string"},
                            },
                            "required": ["assistant_output", "passed", "score", "findings", "summary"],
                        },
                    },
                },
                "safety_identifier": safety_identifier_for(
                    assistant,
                    scenario=scenario,
                    test_input=test_input,
                    expected_output=expected_output,
                ),
                "max_output_tokens": max(16, min(int(_setting("OPENAI_MAX_OUTPUT_TOKENS", 1200)), 4000)),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        retries = max(0, min(int(_setting("OPENAI_MAX_RETRIES", 2)), 3))
        timeout = max(
            float(_setting("OPENAI_CONNECT_TIMEOUT", 5)),
            float(_setting("OPENAI_READ_TIMEOUT", 30)),
        )
        context = ssl.create_default_context()
        last_error = None
        for attempt in range(retries + 1):
            request = Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "saas-collab-governance/production",
                },
            )
            try:
                with urlopen(request, timeout=timeout, context=context) as response:
                    maximum = max(4096, min(int(_setting("OPENAI_MAX_RESPONSE_BYTES", 1048576)), 10_485_760))
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > maximum:
                        raise EvaluationDependencyError("OPENAI_RESPONSE_TOO_LARGE", "OpenAI response exceeded the limit.")
                    raw = response.read(maximum + 1)
                    if len(raw) > maximum:
                        raise EvaluationDependencyError("OPENAI_RESPONSE_TOO_LARGE", "OpenAI response exceeded the limit.")
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise EvaluationDependencyError("OPENAI_RESPONSE_INVALID", "OpenAI returned invalid JSON.") from exc
                provider_status = str(payload.get("status", ""))
                if provider_status != "completed":
                    status_code = {
                        "incomplete": "OPENAI_RESPONSE_INCOMPLETE",
                        "failed": "OPENAI_RESPONSE_FAILED",
                        "cancelled": "OPENAI_RESPONSE_CANCELLED",
                    }.get(provider_status, "OPENAI_RESPONSE_INVALID")
                    # Do not persist response fragments from incomplete or
                    # provider-failed Responses objects.
                    raise EvaluationDependencyError(status_code, "OpenAI evaluation did not complete.")
                raw_output = _output_text(payload)
                structured = _structured_evaluation(raw_output, expected_output)
                return {
                    "response_id": str(payload.get("id", ""))[:255],
                    "model": str(payload.get("model", model))[:120],
                    "token_usage": _sanitized_usage(payload.get("usage")),
                    "result": structured["assistant_output"],
                    **structured,
                }
            except HTTPError as exc:
                last_error = EvaluationDependencyError(
                    f"OPENAI_HTTP_{exc.code}",
                    "OpenAI request failed.",
                    retryable=exc.code in RETRYABLE_HTTP_STATUSES,
                )
                try:
                    exc.close()
                except Exception:
                    pass
            except (URLError, HTTPException, TimeoutError, OSError) as exc:
                last_error = EvaluationDependencyError(
                    "OPENAI_NETWORK_ERROR",
                    "OpenAI request failed.",
                    retryable=True,
                )
            if last_error is None or not last_error.retryable or attempt >= retries:
                break
            delay = min(
                float(_setting("OPENAI_RETRY_BACKOFF", 0.5)) * (2 ** attempt),
                8.0,
            )
            if delay > 0:
                time.sleep(delay)
        raise last_error or EvaluationDependencyError("OPENAI_REQUEST_FAILED", "OpenAI request failed.")


def _save_job(job, fields):
    job._execution_service_write = True
    try:
        job.save(update_fields=[*fields, "updated_at"])
    finally:
        job._execution_service_write = False


def _assistant_is_eligible(assistant, assistant_version):
    allowed_data_classes = {
        str(value).strip()
        for value in (getattr(settings, "GOVERNANCE_EVALUATION_DATA_CLASSES", ("public_demo",)) or ())
        if str(value).strip()
    }
    return (
        assistant.version == assistant_version
        and assistant.status == AssistantDefinition.Status.SANDBOX
        and assistant.data_class in allowed_data_classes
    )


def _fail_evaluation_job_locked(job, *, code, message):
    """Write FAILED only for a currently locked RUNNING evaluation row."""

    if job.status != AssistantEvaluationJob.Status.RUNNING:
        return job
    job.status = AssistantEvaluationJob.Status.FAILED
    job.error_code = code
    job.error_message = message[:1000]
    job.finished_at = timezone.now()
    _save_job(job, ["status", "error_code", "error_message", "finished_at"])
    write_operation_log(
        tenant=job.tenant,
        user=job.requested_by,
        module="governance",
        action="assistant_evaluate_failed",
        object_type="assistant_evaluation_job",
        object_id=job.id,
        after_data={"status": job.status, "error_code": job.error_code, "attempts": job.attempts},
    )
    return job


def _fail_evaluation_job(job, *, code, message):
    # A stale worker may be reporting after the periodic reconciler already
    # closed this row. Re-read under a short row lock and only allow the
    # claimed RUNNING state to transition to FAILED.
    with transaction.atomic():
        current = AssistantEvaluationJob.objects.select_for_update().select_related(
            "tenant", "requested_by",
        ).get(pk=job.pk)
        return _fail_evaluation_job_locked(current, code=code, message=message)


def run_assistant_evaluation_job(job_id):
    """Run one durable evaluation; safe for duplicate Celery deliveries."""

    # Claim only queued work in a short transaction.  The network call below
    # deliberately runs after the lock is released, so duplicate deliveries
    # cannot submit a second provider request or hold a DB lock on I/O.
    with transaction.atomic():
        job = AssistantEvaluationJob.objects.select_for_update().select_related(
            "assistant", "tenant", "requested_by",
        ).get(pk=job_id)
        if job.status != AssistantEvaluationJob.Status.QUEUED:
            return job
        job.status = AssistantEvaluationJob.Status.RUNNING
        job.attempts += 1
        job.started_at = job.started_at or timezone.now()
        _save_job(job, ["status", "attempts", "started_at"])
    try:
        assistant = AssistantDefinition.objects.get(pk=job.assistant_id)
        if not _assistant_is_eligible(assistant, job.assistant_version):
            return _fail_evaluation_job(
                job,
                code="ASSISTANT_VERSION_CHANGED" if assistant.version != job.assistant_version else "ASSISTANT_POLICY_CHANGED",
                message="The approved assistant definition changed before evaluation started.",
            )
        result = OpenAIResponsesClient().evaluate(
            assistant,
            scenario=job.scenario,
            test_input=job.test_input,
            expected_output=job.expected_output,
            reason=job.reason,
        )
    except EvaluationDependencyError as exc:
        return _fail_evaluation_job(job, code=exc.code, message=str(exc))
    except Exception:
        # Never persist provider exception text: it can contain request data.
        return _fail_evaluation_job(job, code="EVALUATION_FAILED", message="Assistant evaluation failed.")

    # Reacquire both rows after provider I/O. The reconciler may have marked a
    # lost worker failed, and the assistant definition may have been disabled
    # or versioned while the network request was in flight. The two locks keep
    # the final eligibility decision and terminal write in one short
    # transaction; a stale worker can neither resurrect a job nor persist a
    # result for a changed definition.
    with transaction.atomic():
        current = AssistantEvaluationJob.objects.select_for_update().select_related(
            "tenant", "requested_by",
        ).get(pk=job.pk)
        if current.status != AssistantEvaluationJob.Status.RUNNING:
            return current
        try:
            current_assistant = AssistantDefinition.objects.select_for_update().get(pk=current.assistant_id)
        except AssistantDefinition.DoesNotExist:
            return _fail_evaluation_job_locked(
                current,
                code="ASSISTANT_POLICY_CHANGED",
                message="The approved assistant definition is no longer available.",
            )
        if not _assistant_is_eligible(current_assistant, current.assistant_version):
            return _fail_evaluation_job_locked(
                current,
                code="ASSISTANT_VERSION_CHANGED" if current_assistant.version != current.assistant_version else "ASSISTANT_POLICY_CHANGED",
                message="The approved assistant definition changed during evaluation.",
            )
        current.status = AssistantEvaluationJob.Status.SUCCEEDED
        current.response_id = result["response_id"]
        current.model = result["model"]
        current.token_usage = result["token_usage"]
        current.result = result["result"][:MAX_RESULT_CHARS]
        current.assistant_output = result["assistant_output"][:MAX_RESULT_CHARS]
        current.passed = result["passed"]
        current.score = result["score"]
        current.findings = result["findings"]
        current.result_summary = result["result_summary"][:1000]
        current.error_code = ""
        current.error_message = ""
        current.finished_at = timezone.now()
        _save_job(
            current,
            [
                "status", "response_id", "model", "token_usage", "result", "assistant_output",
                "passed", "score", "findings", "result_summary", "error_code", "error_message", "finished_at",
            ],
        )
        write_operation_log(
            tenant=current.tenant,
            user=current.requested_by,
            module="governance",
            action="assistant_evaluate_succeeded",
            object_type="assistant_evaluation_job",
            object_id=current.id,
            after_data={"status": current.status, "model": current.model, "response_id": current.response_id, "attempts": current.attempts},
        )
        return current

"""Bounded HTTPS transport for approved marketplace and custody hosts."""

import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import stat
import time
import urllib.parse
from dataclasses import dataclass

from django.conf import settings

from .oauth_errors import (
    OAUTH_AUTH_REJECTED,
    OAUTH_PROVIDER_ERROR,
    OAUTH_PROVIDER_UNAVAILABLE,
    OAUTH_RATE_LIMITED,
    OAuthFlowError,
)

MAX_RESPONSE_BYTES = 1024 * 1024


@dataclass
class HttpResponse:
    status_code: int
    headers: dict
    text: str

    def json(self):
        return json.loads(self.text)


def get_allowed_hosts():
    hosts = {str(host).lower() for host in (getattr(settings, "LIVE_PLATFORM_ALLOWED_HOSTS", []) or [])}
    custody = str(getattr(settings, "LIVE_CUSTODY_SERVICE_HOST", "") or "").lower()
    if custody:
        hosts.add(custody)
    custody_url = str(getattr(settings, "LIVE_CUSTODY_SERVICE_URL", "") or "").strip()
    try:
        custody_parsed = urllib.parse.urlparse(custody_url)
    except (TypeError, ValueError):
        custody_parsed = None
    if custody_parsed is not None and custody_parsed.hostname:
        hosts.add(custody_parsed.hostname.lower())
    return hosts


def _configured_custody_endpoint():
    """Return the exact custody host/port tuple allowed for non-443 traffic."""
    raw_url = str(getattr(settings, "LIVE_CUSTODY_SERVICE_URL", "") or "").strip()
    if not raw_url:
        return None
    try:
        parsed = urllib.parse.urlparse(raw_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            return None
        return parsed.hostname.lower(), parsed.port or 443
    except (TypeError, ValueError):
        return None


def _is_configured_custody_destination(parsed):
    endpoint = _configured_custody_endpoint()
    if endpoint is None or not parsed.hostname:
        return False
    try:
        port = parsed.port or 443
    except ValueError:
        return False
    return parsed.scheme == "https" and (parsed.hostname.lower(), port) == endpoint


def _validated_custody_ca_file():
    """Validate the optional custody CA path before handing it to SSL."""
    raw_path = str(getattr(settings, "LIVE_CUSTODY_CA_FILE", "") or "").strip()
    if not raw_path:
        return ""
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Custody CA file must be an absolute path.")
    try:
        file_stat = candidate.lstat()
    except OSError:
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Custody CA file is unavailable.") from None
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Custody CA file is unavailable.")
    if os.name != "nt":
        mode = stat.S_IMODE(file_stat.st_mode)
        if mode & 0o077 or mode & 0o111 or not mode & 0o400 or mode not in {0o400, 0o600}:
            raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Custody CA file permissions are unsafe.")
    return str(candidate)


def assert_host_allowed(url):
    try:
        parsed = urllib.parse.urlparse(str(url))
    except (TypeError, ValueError):
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Only approved HTTPS destinations are permitted.") from None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Only approved HTTPS destinations are permitted.")
    try:
        configured_custody = _is_configured_custody_destination(parsed)
        port = parsed.port
    except ValueError:
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Only approved HTTPS destinations are permitted.") from None
    # Platform API traffic remains pinned to HTTPS/443.  A non-standard port
    # is permitted only when the complete host/port pair matches the exact
    # independently configured custody URL.
    if port not in (None, 443) and not configured_custody:
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Non-standard outbound ports are not permitted.")
    if parsed.hostname.lower() not in get_allowed_hosts():
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Outbound host is not approved.")


def _bounded_float(value, *, minimum, maximum, name):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, f"Invalid {name} configuration.") from exc
    if number < minimum or number > maximum:
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, f"{name} is outside the approved bound.")
    return number


def _default_transport(method, url, *, data=None, headers=None, connect_timeout=None, read_timeout=None):
    """Perform one request with independent connect/read timeouts and CA validation."""
    parsed = urllib.parse.urlparse(url)
    tls_context = ssl.create_default_context()
    if _is_configured_custody_destination(parsed):
        ca_file = _validated_custody_ca_file()
        if ca_file:
            # Keep the public system trust store and add the private custody
            # CA only for this exact configured host/port.
            tls_context.load_verify_locations(cafile=ca_file)
    connection = http.client.HTTPSConnection(
        parsed.hostname,
        parsed.port or 443,
        timeout=connect_timeout,
        context=tls_context,
    )
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    try:
        connection.request(method.upper(), path, body=data, headers=headers or {})
        if connection.sock is not None:
            connection.sock.settimeout(read_timeout)
        response = connection.getresponse()
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise OSError("platform response exceeded the approved size limit")
        return HttpResponse(
            status_code=response.status,
            headers={str(key).lower(): value for key, value in response.getheaders()},
            text=body.decode("utf-8", "replace"),
        )
    finally:
        connection.close()


class PlatformHttpClient:
    def __init__(self, transport=None, max_retries=None, backoff_base=None, sleeper=None):
        self._transport = transport or _default_transport
        self.max_retries = int(
            max_retries if max_retries is not None else getattr(settings, "LIVE_PLATFORM_MAX_RETRIES", 2)
        )
        if self.max_retries < 0 or self.max_retries > 5:
            raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Retry count is outside the approved bound.")
        self.backoff_base = _bounded_float(
            backoff_base if backoff_base is not None else getattr(settings, "LIVE_PLATFORM_BACKOFF_BASE", 0.5),
            minimum=0.0,
            maximum=5.0,
            name="retry backoff",
        )
        self.max_retry_wait = _bounded_float(
            getattr(settings, "LIVE_PLATFORM_MAX_RETRY_WAIT", 8), minimum=0.0, maximum=30.0, name="retry wait"
        )
        self.max_total_wait = _bounded_float(
            getattr(settings, "LIVE_PLATFORM_MAX_TOTAL_WAIT", 15), minimum=0.0, maximum=60.0, name="total retry wait"
        )
        self._sleep = sleeper or time.sleep

    def _delay(self, attempt, response=None, waited=0.0):
        retry_after = None
        if response is not None:
            retry_after = response.headers.get("retry-after") or response.headers.get("Retry-After")
        try:
            requested = float(retry_after) if retry_after is not None else None
        except (TypeError, ValueError):
            requested = None
        delay = requested if requested is not None and requested >= 0 else self.backoff_base * (2 ** attempt)
        delay = min(delay, self.max_retry_wait)
        return min(delay, max(0.0, self.max_total_wait - waited))

    def request(
        self,
        method,
        url,
        *,
        json_body=None,
        form_body=None,
        headers=None,
        connect_timeout=None,
        read_timeout=None,
    ):
        assert_host_allowed(url)
        data = None
        request_headers = dict(headers or {})
        if json_body is not None:
            data = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        elif form_body is not None:
            data = urllib.parse.urlencode(form_body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

        connect_timeout = _bounded_float(
            connect_timeout if connect_timeout is not None else getattr(settings, "LIVE_PLATFORM_CONNECT_TIMEOUT", 3),
            minimum=0.1,
            maximum=10.0,
            name="connect timeout",
        )
        read_timeout = _bounded_float(
            read_timeout if read_timeout is not None else getattr(settings, "LIVE_PLATFORM_READ_TIMEOUT", 8),
            minimum=0.1,
            maximum=30.0,
            name="read timeout",
        )

        waited = 0.0
        last_error = OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Platform request failed.")
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                response = self._transport(
                    method,
                    url,
                    data=data,
                    headers=request_headers,
                    connect_timeout=connect_timeout,
                    read_timeout=read_timeout,
                )
            except (socket.timeout, TimeoutError):
                last_error = OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Platform request timed out.")
            except ssl.SSLError:
                last_error = OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "TLS validation failed.")
            except (socket.gaierror, ConnectionError, ConnectionResetError, OSError):
                last_error = OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Platform network request failed.")
            except OAuthFlowError:
                raise

            if response is not None:
                status = response.status_code
                if 200 <= status < 400:
                    return response
                if status == 429:
                    last_error = OAuthFlowError(OAUTH_RATE_LIMITED, "Platform rate limit reached.")
                elif 500 <= status <= 599:
                    last_error = OAuthFlowError(OAUTH_PROVIDER_ERROR, "Platform service error.")
                elif status in (401, 403):
                    raise OAuthFlowError(OAUTH_AUTH_REJECTED, "Platform rejected authorization.")
                else:
                    raise OAuthFlowError(OAUTH_PROVIDER_ERROR, "Platform rejected the request.")

            if attempt >= self.max_retries or waited >= self.max_total_wait:
                raise last_error
            delay = self._delay(attempt, response=response, waited=waited)
            if delay <= 0:
                raise last_error
            self._sleep(delay)
            waited += delay
        raise last_error

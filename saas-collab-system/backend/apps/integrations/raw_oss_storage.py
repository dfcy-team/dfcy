"""Private, bounded Django storage for immutable RAW payload objects."""

import io
import json
import os
import re
import stat
from urllib.parse import urlsplit

from django.core.files.base import File
from django.core.files.storage import Storage

from alibabacloud_oss_v2 import Client, credentials, models, transport
from alibabacloud_oss_v2.config import Config


MAX_OBJECT_BYTES = 32 * 1024 * 1024
MAX_CREDENTIAL_FILE_BYTES = 16 * 1024
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
_REGION_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KEY_RE = re.compile(r"^raw/(?P<namespace>[A-Za-z0-9][A-Za-z0-9._-]{0,63})/tenant-[0-9]+/(?P<uuid>[0-9a-f]{32})\.json\.gz$")


class RawOSSStorageError(Exception):
    """Safe fixed-message storage error; provider details are intentionally hidden."""


class PrivateRawOSSStorage(Storage):
    def __init__(self, endpoint, region, bucket, credential_file, namespace,
                 connect_timeout=3, read_timeout=15):
        super().__init__()
        if not isinstance(region, str) or not _REGION_RE.fullmatch(region):
            raise ValueError("Invalid OSS region.")
        self.endpoint = self._validate_endpoint(endpoint, region)
        if not isinstance(bucket, str) or not _BUCKET_RE.fullmatch(bucket):
            raise ValueError("Invalid OSS bucket.")
        if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace):
            raise ValueError("Invalid RAW storage namespace.")
        self.region = region
        self.bucket = bucket
        self.namespace = namespace
        self.credential_file = os.fspath(credential_file)
        self.connect_timeout = self._validate_timeout(connect_timeout)
        self.read_timeout = self._validate_timeout(read_timeout)

    @staticmethod
    def _validate_endpoint(endpoint, region):
        if not isinstance(endpoint, str):
            raise ValueError("Invalid OSS endpoint.")
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.port is not None or parsed.path or parsed.query or parsed.fragment
                or parsed.hostname not in {
                    f"oss-{region}.aliyuncs.com",
                    f"oss-{region}-internal.aliyuncs.com",
                }):
            raise ValueError("Invalid OSS endpoint.")
        return f"https://{parsed.hostname}"

    @staticmethod
    def _validate_timeout(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 120:
            raise ValueError("OSS timeouts must be greater than 0 and at most 120 seconds.")
        return value

    def _validate_key(self, name):
        if not isinstance(name, str):
            raise ValueError("Invalid RAW object key.")
        match = _KEY_RE.fullmatch(name)
        if not match or match.group("namespace") != self.namespace:
            raise ValueError("Invalid RAW object key.")
        return name

    def _load_credentials(self):
        try:
            # A misconfigured FIFO must not block before the regular-file check.
            flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
                     | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            descriptor = os.open(self.credential_file, flags)
            with os.fdopen(descriptor, "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CREDENTIAL_FILE_BYTES:
                    raise ValueError
                if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
                    raise ValueError
                raw = source.read(MAX_CREDENTIAL_FILE_BYTES + 1)
            if len(raw) > MAX_CREDENTIAL_FILE_BYTES:
                raise ValueError
            data = json.loads(raw.decode("utf-8"))
            access_key_id = data["access_key_id"]
            access_key_secret = data["access_key_secret"]
            token = data.get("security_token")
            if (not isinstance(access_key_id, str) or not access_key_id
                    or not isinstance(access_key_secret, str) or not access_key_secret
                    or (token is not None and (not isinstance(token, str) or not token))):
                raise ValueError
            return credentials.StaticCredentialsProvider(
                access_key_id=access_key_id,
                access_key_secret=access_key_secret,
                security_token=token,
            )
        except Exception:
            raise RawOSSStorageError("OSS credentials are unavailable or invalid.") from None

    def _client(self):
        provider = self._load_credentials()
        http = transport.RequestsHttpClient(
            connect_timeout=self.connect_timeout,
            readwrite_timeout=self.read_timeout,
            enabled_redirect=False,
            insecure_skip_verify=False,
        )
        try:
            config = Config(
                region=self.region,
                endpoint=self.endpoint,
                credentials_provider=provider,
                retry_max_attempts=1,
                http_client=http,
                connect_timeout=self.connect_timeout,
                readwrite_timeout=self.read_timeout,
                disable_ssl=False,
                insecure_skip_verify=False,
                enabled_redirect=False,
            )
            return Client(config), http
        except Exception:
            http.close()
            raise RawOSSStorageError("OSS client initialization failed.") from None

    def save(self, name, content, max_length=None):
        # Django's default save() probes exists() and may silently rename a key.
        self._validate_key(name)
        if max_length is not None and len(name) > max_length:
            raise ValueError("RAW object key exceeds the maximum name length.")
        return self._save(name, content)

    def _save(self, name, content):
        self._validate_key(name)
        try:
            body = content.read(MAX_OBJECT_BYTES + 1)
            if not isinstance(body, bytes) or len(body) > MAX_OBJECT_BYTES:
                raise RawOSSStorageError("RAW object exceeds the configured size limit.")
        except RawOSSStorageError:
            raise
        except Exception:
            raise RawOSSStorageError("RAW object could not be read.") from None
        client, http = self._client()
        try:
            client.put_object(models.PutObjectRequest(
                bucket=self.bucket,
                key=name,
                body=body,
                content_length=len(body),
                acl="private",
                server_side_encryption="AES256",
                forbid_overwrite=True,
            ))
            return name
        except Exception:
            raise RawOSSStorageError("RAW object upload failed.") from None
        finally:
            http.close()

    def _open(self, name, mode="rb"):
        self._validate_key(name)
        if mode != "rb":
            raise ValueError("RAW objects can only be opened in binary read mode.")
        client, http = self._client()
        stream = None
        try:
            result = client.get_object(models.GetObjectRequest(bucket=self.bucket, key=name))
            stream = result.body
            collected = bytearray()
            for chunk in stream.iter_bytes(block_size=64 * 1024):
                collected.extend(chunk)
                if len(collected) > MAX_OBJECT_BYTES:
                    raise RawOSSStorageError("RAW object exceeds the configured size limit.")
            return File(io.BytesIO(collected), name=name)
        except RawOSSStorageError:
            raise
        except Exception:
            raise RawOSSStorageError("RAW object download failed.") from None
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            http.close()

    def exists(self, name):
        raise NotImplementedError("RAW object existence checks are not supported.")

    def url(self, name):
        raise NotImplementedError("Private RAW objects do not have public URLs.")

    def delete(self, name):
        raise NotImplementedError("RAW object deletion is not supported.")

    def listdir(self, path):
        raise NotImplementedError("RAW object listing is not supported.")

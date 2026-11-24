"""Bounded HTTPS voucher download. Hosts must be explicitly pinned per mapping."""
import http.client
import ipaddress
import socket
import ssl
import time
import re
from urllib.parse import urlsplit
from .feishu_finance_form import MAX_FILE_BYTES, FinanceFormError, validate_finance_file
from .net_guard import _destination_https_proxy


def download_finance_file(item, *, allowed_hosts):
    url = item.get('url', '')
    parsed = urlsplit(url)
    hosts = {str(h).lower() for h in allowed_hosts}
    provider_host = bool(re.fullmatch(r'(?:p[0-9]+-approval-sign\.byteimg\.com|p[0-9]+-hera\.feishucdn\.com|sf[0-9]+(?:-[a-z0-9]+)?\.feishucdn\.com)',parsed.hostname or ''))
    host_allowed = parsed.hostname and (parsed.hostname.lower() in hosts or ('feishu-approval-cdn' in hosts and provider_host))
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or
            parsed.port not in (None,443) or parsed.fragment or not host_allowed):
        raise FinanceFormError('voucher download host is not approved')
    try:
        addresses = socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise FinanceFormError('voucher download destination is not public')
        proxy = _destination_https_proxy(parsed)
        conn = http.client.HTTPSConnection(*(proxy or (parsed.hostname,443)),timeout=3,context=ssl.create_default_context())
        try:
            if proxy:conn.set_tunnel(parsed.hostname,443)
            path = parsed.path or '/'
            if parsed.query:path += '?' + parsed.query
            # Signed URLs are sufficient. Never forward a tenant access token.
            conn.request('GET',path,headers={'Accept':'application/pdf,image/png,image/jpeg,application/octet-stream'})
            if conn.sock is not None:conn.sock.settimeout(8)
            response = conn.getresponse()
            if response.status != 200:raise FinanceFormError('voucher download failed or redirected')
            length = response.getheader('Content-Length')
            if length and (not length.isdigit() or int(length)>MAX_FILE_BYTES):raise FinanceFormError('voucher exceeds size limit')
            chunks=[];size=0;started=time.monotonic()
            while True:
                chunk=response.read(min(65536,MAX_FILE_BYTES+1-size))
                if not chunk:break
                chunks.append(chunk);size+=len(chunk)
                if size>MAX_FILE_BYTES or time.monotonic()-started>30:raise FinanceFormError('voucher size or time limit exceeded')
            content=b''.join(chunks)
            meta=validate_finance_file(content,declared_name=item['name'],content_type=response.getheader('Content-Type','application/octet-stream'))
            return {'source_key':item['source_key'],'file_name':meta['filename'],'content':content,**meta}
        finally:conn.close()
    except FinanceFormError:raise
    except Exception:
        # Error details must never include a signed download URL.
        raise FinanceFormError('voucher download unavailable') from None

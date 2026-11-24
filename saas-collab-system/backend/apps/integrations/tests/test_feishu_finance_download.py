import pytest

from apps.integrations.feishu_finance_download import download_finance_file
from apps.integrations.feishu_finance_form import FinanceFormError


class Response:
    status = 200
    def read(self, size):
        if not hasattr(self, 'done'):
            self.done = True
            return b'%PDF-1.7 synthetic voucher'
        return b''
    def getheader(self, key, default=None):
        return {'Content-Type': 'application/pdf', 'Content-Length': '26'}.get(key, default)


class Connection:
    sock = None
    def __init__(self, *args, **kwargs):
        self.request_args = None
    def request(self, *args, **kwargs):
        self.request_args = (args, kwargs)
    def getresponse(self):
        return Response()
    def close(self):
        pass


def test_download_pinned_https_file_without_forwarding_credentials(monkeypatch):
    connections = []
    def connect(*args, **kwargs):
        row = Connection(*args, **kwargs)
        connections.append(row)
        return row
    monkeypatch.setattr('apps.integrations.feishu_finance_download.socket.getaddrinfo',
                        lambda *a, **k: [(None, None, None, None, ('8.8.8.8', 443))])
    monkeypatch.setattr('apps.integrations.feishu_finance_download.http.client.HTTPSConnection', connect)
    result = download_finance_file({'url': 'https://files.example/voucher?sig=secret', 'name': 'receipt.pdf', 'source_key': 'opaque'}, allowed_hosts=['files.example'])
    assert result['content'].startswith(b'%PDF-1.7')
    assert result['source_key'] == 'opaque'
    assert connections[0].request_args[1]['headers'] == {'Accept': 'application/pdf,image/png,image/jpeg,application/octet-stream'}


@pytest.mark.parametrize('url', [
    'http://files.example/receipt.pdf',
    'https://evil.example/receipt.pdf',
    'https://user@files.example/receipt.pdf',
    'https://files.example:444/receipt.pdf',
])
def test_download_rejects_unpinned_or_unsafe_urls_before_network(url, monkeypatch):
    monkeypatch.setattr('apps.integrations.feishu_finance_download.socket.getaddrinfo',
                        lambda *a, **k: pytest.fail('must reject before DNS'))
    with pytest.raises(FinanceFormError):
        download_finance_file({'url': url, 'name': 'receipt.pdf', 'source_key': 'opaque'}, allowed_hosts=['files.example'])

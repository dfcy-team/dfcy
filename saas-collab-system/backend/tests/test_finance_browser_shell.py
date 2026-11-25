import gzip
import hashlib
import json
from pathlib import Path

from apps.finance.summary_views import browser_document, presentation_stamp


def test_calculation_only_template_has_a_browser_shell_and_ready_bridge():
    root = Path(__file__).parents[1] / 'apps/finance/templates'
    source = gzip.decompress((root / 'database-v1.html.gz').read_bytes()).decode()
    assert '<head>' not in source
    document = browser_document(source)
    assert '<head>' in document and '<body>' in document
    assert 'finance-summary-ready' in document
    assert 'id="ledger-table"' in document
    assert 'id="filters"' in document
    assert document.index('globalThis.SAAS_STORAGE=') < document.index('id="snapshot"')
    assert "const screen={shop:'SP6TH'" not in document
    assert 'shop:data.shops[0]?.code' in document


def test_settings_shell_contains_only_markup_and_has_an_integrity_manifest():
    root = Path(__file__).parents[1] / 'apps/finance/templates'
    shell = (root / 'settings-shell-v1.html').read_bytes()
    manifest = json.loads((root / 'settings-shell-v1.json').read_text())
    assert hashlib.sha256(shell).hexdigest() == manifest['sha256']
    assert manifest['contains_business_data'] is False
    assert b'<script' not in shell.lower()
    assert b'SPKJ1PH1' not in shell and b'https://' not in shell
    assert shell.count(b'<!-- SAAS_FINANCE_CALCULATION_SCRIPTS -->') == 1
    assert len(presentation_stamp()) >= 12


def test_existing_full_document_is_not_given_a_second_shell():
    document = browser_document('<html><head></head><body><div id="existing">Existing</div></body></html>')
    assert document.count('<head>') == 1
    assert 'id="existing"' in document
    assert 'id="ledger-table"' not in document

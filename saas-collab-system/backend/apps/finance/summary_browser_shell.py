"""Supply data-free DOM for batches built from the calculation-only template."""
import hashlib
import json
from pathlib import Path
import re

from rest_framework.exceptions import ValidationError


def with_browser_shell(document):
    if re.search(r'<head(?:\s|>)', document, re.IGNORECASE):
        return document
    if 'id="snapshot"' not in document or 'id="html2-ledger-fees"' not in document:
        raise ValidationError('财务设置模板不完整，未加载设置页面。')
    root = Path(__file__).with_name('templates')
    shell = (root / 'settings-shell-v1.html').read_bytes()
    layout = (root / 'settings-layout-v1.js').read_bytes()
    manifest = json.loads((root / 'settings-shell-v1.json').read_text(encoding='utf-8'))
    marker = '<!-- SAAS_FINANCE_CALCULATION_SCRIPTS -->'
    if (hashlib.sha256(shell).hexdigest() != manifest['sha256']
            or hashlib.sha256(layout).hexdigest() != manifest['layout_sha256']
            or manifest.get('contains_business_data') is not False
            or shell.count(marker.encode()) != 1):
        raise ValidationError('财务设置界面模板校验失败，未加载设置页面。')
    if 'id="html2-layout"' not in document:
        document += '\n<script id="html2-layout">' + layout.decode('utf-8') + '</script>'
    return shell.decode('utf-8').replace(marker, document)

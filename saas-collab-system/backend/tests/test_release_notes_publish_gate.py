"""Execute the real publisher gate against synthetic notes, without publishing."""
import json
import re
from pathlib import Path

import pytest


@pytest.mark.parametrize('requested,latest,passes', [
    ('2.44.369', '2.44.369', True),
    ('2.44.372', '2.44.369', False),
    ('', '2.44.369', False),
    ('2.44.369;echo unsafe', '2.44.369', False),
])
def test_publish_gate_rejects_stale_or_invalid_version(tmp_path, monkeypatch, requested, latest, passes):
    root = Path(__file__).resolve().parents[3]
    text = (root / '.github/workflows/production-artifacts-build-only.yml').read_text(encoding='utf-8')
    assert 'release_version:\n' in text
    assert text.index('Require release notes to match the requested release') < text.index('Publish uniquely named backend build')
    block = text.split('Require release notes to match the requested release', 1)[1]
    code = re.search(r"python - <<'PY'\n(.*?)\n\s+PY", block, re.S).group(1)
    code = '\n'.join(line[10:] for line in code.splitlines())
    notes = tmp_path / 'saas-collab-system/frontend/src/data/releaseNotes.json'
    notes.parent.mkdir(parents=True)
    notes.write_text(json.dumps([{'version': latest}]), encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('EXPECTED_RELEASE_VERSION', requested)
    if passes:
        exec(compile(code, '<actual-workflow-gate>', 'exec'), {})
    else:
        with pytest.raises(AssertionError):
            exec(compile(code, '<actual-workflow-gate>', 'exec'), {})

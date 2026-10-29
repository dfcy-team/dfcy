from pathlib import Path
import os
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INSTALL = (ROOT / "bin/install-control.sh").read_text(encoding="utf-8")


def test_legacy_batch_preflight_is_not_installed_or_granted_sudo():
    assert "production-image-preflight-batch317-320" not in INSTALL
    line = next(line for line in INSTALL.splitlines() if "Cmnd_Alias SAAS_COLLAB_RELEASE_CONTROL" in line)
    assert "preflight-batch317-320" not in line
    assert "%s/bin/production-deploy *" in line


def test_v330_preflight_is_installed_hashed_and_narrowly_authorized():
    assert "production-image-preflight-v330" in INSTALL
    assert "config/v330-release-identity.json" in INSTALL
    assert "config/v330-controller-approval.json" not in INSTALL
    line = next(line for line in INSTALL.splitlines() if "Cmnd_Alias SAAS_COLLAB_RELEASE_CONTROL" in line)
    assert "%s/bin/production-image-preflight-v330 --build-run-id=* --build-controller-sha=* --manifest-sha256=* --receipt-sha256=* --registry-user=*" in line


def test_installer_writes_readable_root_sudo_marker_and_absolute_baseline_paths():
    assert '"$CONTROL_ROOT/use-sudo"' in INSTALL
    assert 'chmod 644 "$CONTROL_ROOT/use-sudo"' in INSTALL
    assert '"$CONTROL_ROOT/config/use-sudo"' not in INSTALL
    assert '"$CONTROL_ROOT/bin/developer-a-ci-dispatch"' in INSTALL
    assert 'cd "$CONTROL_ROOT"' not in INSTALL


def test_generated_baseline_verifies_from_filesystem_root(tmp_path):
    block = INSTALL.split('    sha256sum \\\n', 1)[1].split('    control_env=', 1)[0]
    names = re.findall(r'\$CONTROL_ROOT/([^"\n]+)', block)
    assert len(names) >= 13
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('fixture:' + name, encoding='utf-8')
    bash = str(Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Git/bin/bash.exe') if os.name == 'nt' else shutil.which('bash')
    assert bash
    setup = 'CONTROL_ROOT=$(cygpath -u "$1")' if os.name == 'nt' else 'CONTROL_ROOT=$1'
    script = setup + '\nsha256sum \\\n' + block + '> "$CONTROL_ROOT/baseline.sha256"\ncd /\nsha256sum -c "$CONTROL_ROOT/baseline.sha256"\n'
    # Attach the redirect to the actual installer command rather than a new command.
    script = script.replace('\n> "$CONTROL_ROOT/baseline.sha256"', ' > "$CONTROL_ROOT/baseline.sha256"')
    result = subprocess.run([bash, '-c', script, 'baseline-test', str(tmp_path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count(': OK') == len(names)

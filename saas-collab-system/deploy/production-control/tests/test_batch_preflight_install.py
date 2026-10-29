from pathlib import Path

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

"""Align only the credentials worker parser with the verified backend source."""
import hashlib
from pathlib import Path
import subprocess

container = "production-celery-credentials-1"
path = "/app/apps/integrations/production_settings.py"
root = Path("/opt/saas-collab/production/hotfix-credential-config-20261102")
old_hash = "a5aa374a138099ca757257ffbc04ad7531ea5996e58d5017b83b0c36344cbe50"
new_hash = "adec2d0ba24198abde958bbad3c0e7a6736e57b0034e38343f06f87beb74e314"
old = subprocess.check_output(["docker", "exec", container, "cat", path])
new = subprocess.check_output(["docker", "exec", "production-backend-1", "cat", path])
assert hashlib.sha256(old).hexdigest() == old_hash, "Worker drift"
assert hashlib.sha256(new).hexdigest() == new_hash, "Backend drift"
compile(new, path, "exec")
root.mkdir(exist_ok=True)
backup = root / "production_settings.py.before"
assert not backup.exists(), "Already deployed; inspect before repeating"
backup.write_bytes(old)
source = root / "production_settings.py"
source.write_bytes(new)
subprocess.run(["docker", "cp", str(source), container + ":" + path], check=True)
assert subprocess.check_output(["docker", "exec", container, "cat", path]) == new
print("Parser aligned and backed up; no restart or token operation performed.")

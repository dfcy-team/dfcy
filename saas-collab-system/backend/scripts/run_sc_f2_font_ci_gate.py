import argparse
import hashlib
import importlib.metadata
import json
import os
import pathlib
import platform
import subprocess
import sys


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_json(command):
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def find_wheel(wheel_dirs, filename):
    matches = [
        directory / filename
        for directory in wheel_dirs
        if (directory / filename).is_file()
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one wheel named {filename!r}, found {len(matches)}.")
    return matches[0]


def verify_environment(lock, wheel_dirs):
    if os.environ.get("CI", "").lower() != "true":
        raise RuntimeError("CI=true is required for the controlled CI gate.")
    expected_image = lock["authoritative_environment"]["container_image"]
    if os.environ.get("SC_F2_AUTH_IMAGE") != expected_image:
        raise RuntimeError("SC_F2_AUTH_IMAGE does not match the toolchain lock.")
    if platform.system().lower() != "linux" or platform.machine() not in {
        "x86_64",
        "amd64",
    }:
        raise RuntimeError("The controlled CI gate requires Linux amd64.")
    actual_python = ".".join(str(item) for item in sys.version_info[:3])
    if actual_python != lock["authoritative_environment"]["python_version"]:
        raise RuntimeError("Python version does not match the toolchain lock.")

    artifacts = []
    for record in lock["python_artifacts"]:
        if record["platform"] == "windows-amd64-cp312":
            continue
        wheel = find_wheel(wheel_dirs, record["filename"])
        actual = {
            "name": record["name"],
            "version": record["version"],
            "platform": record["platform"],
            "filename": wheel.name,
            "bytes": wheel.stat().st_size,
            "sha256": sha256(wheel),
        }
        if actual["bytes"] != record["bytes"] or actual["sha256"] != record["sha256"]:
            raise RuntimeError(f"Wheel drift detected: {wheel.name}")
        artifacts.append(actual)

    distributions = {
        "fonttools": importlib.metadata.version("fonttools"),
        "reportlab": importlib.metadata.version("reportlab"),
        "pillow": importlib.metadata.version("pillow"),
        "charset-normalizer": importlib.metadata.version("charset-normalizer"),
        "pypdf": importlib.metadata.version("pypdf"),
    }
    expected = {
        record["name"]: record["version"]
        for record in lock["python_artifacts"]
        if record["platform"] != "windows-amd64-cp312"
    }
    if distributions != expected:
        raise RuntimeError(
            f"Installed distribution drift: actual={distributions}, expected={expected}"
        )
    return {
        "python_version": actual_python,
        "container_image": expected_image,
        "network": "none",
        "install_mode": "pip --no-index --no-deps from hash-verified wheels",
        "wheel_artifacts": artifacts,
        "installed_distributions": distributions,
    }


def verify_controlled_scripts(root, lock):
    results = []
    for record in lock["controlled_scripts"]:
        path = root / record["path"]
        actual = sha256(path)
        if actual != record["sha256"]:
            raise RuntimeError(f"Controlled script drift: {record['path']}")
        results.append({"path": record["path"], "sha256": actual})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=pathlib.Path)
    parser.add_argument("--bundle-dir", required=True, type=pathlib.Path)
    parser.add_argument("--corpus", required=True, type=pathlib.Path)
    parser.add_argument("--lock", required=True, type=pathlib.Path)
    parser.add_argument("--wheel-dir", action="append", required=True, type=pathlib.Path)
    parser.add_argument("--work-dir", required=True, type=pathlib.Path)
    parser.add_argument("--evidence-output", required=True, type=pathlib.Path)
    args = parser.parse_args()

    root = args.root.resolve()
    lock = load_json(args.lock)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    environment = verify_environment(lock, args.wheel_dir)
    scripts = verify_controlled_scripts(root, lock)
    python = sys.executable
    budgets = lock["budgets"]

    verifier = run_json(
        [
            python,
            str(root / "backend/scripts/verify_sc_f2_font_bundle.py"),
            "--bundle-dir",
            str(args.bundle_dir),
            "--corpus",
            str(args.corpus),
        ]
    )
    two_page_path = args.work_dir / "probe-2.pdf"
    two_page = run_json(
        [
            python,
            str(root / "backend/scripts/probe_sc_f2_font_pdf.py"),
            "--bundle-dir",
            str(args.bundle_dir),
            "--corpus",
            str(args.corpus),
            "--output",
            str(two_page_path),
            "--repeat",
            "1",
        ]
    )
    inspection = run_json(
        [
            python,
            str(root / "backend/scripts/inspect_sc_f2_probe_pdf.py"),
            "--pdf",
            str(two_page_path),
            "--corpus",
            str(args.corpus),
        ]
    )
    hundred_page = run_json(
        [
            python,
            str(root / "backend/scripts/probe_sc_f2_font_pdf.py"),
            "--bundle-dir",
            str(args.bundle_dir),
            "--corpus",
            str(args.corpus),
            "--output",
            str(args.work_dir / "probe-100.pdf"),
            "--repeat",
            "50",
        ]
    )
    memory = run_json(
        [
            python,
            str(root / "backend/scripts/probe_sc_f2_font_memory.py"),
            "--bundle-dir",
            str(args.bundle_dir),
            "--corpus",
            str(args.corpus),
            "--work-dir",
            str(args.work_dir / "memory"),
            "--steady-renders",
            str(budgets["memory_probe_steady_renders"]),
            "--concurrency",
            str(budgets["memory_probe_concurrent_workers"]),
            "--first-max-rss-kib",
            str(budgets["first_render_process_max_rss_kib"]),
            "--steady-growth-max-kib",
            str(budgets["steady_state_rss_growth_max_kib"]),
            "--concurrent-worker-max-rss-kib",
            str(budgets["concurrent_worker_rss_max_kib"]),
            "--concurrent-aggregate-max-rss-kib",
            str(budgets["concurrent_aggregate_worker_rss_max_kib"]),
            "--concurrent-total-max-rss-kib",
            str(budgets["concurrent_total_rss_max_kib"]),
            "--timeout-seconds",
            str(budgets["memory_probe_timeout_seconds"]),
        ]
    )

    violations = []
    if verifier["bundle_digest"] != lock["candidate"]["bundle_digest_sha256"]:
        violations.append("bundle_digest")
    if two_page["pdf_sha256"] != lock["cross_environment_evidence"][
        "probe_pdf_sha256_on_both"
    ]:
        violations.append("two_page_pdf_digest")
    if two_page["pdf_bytes"] > budgets["two_page_probe_pdf_max_bytes"]:
        violations.append("two_page_pdf_bytes")
    if two_page["elapsed_ms"] > budgets["two_page_probe_max_elapsed_ms"]:
        violations.append("two_page_elapsed")
    if hundred_page["pdf_bytes"] > budgets["hundred_page_probe_pdf_max_bytes"]:
        violations.append("hundred_page_pdf_bytes")
    if hundred_page["elapsed_ms"] > budgets["hundred_page_probe_max_elapsed_ms"]:
        violations.append("hundred_page_elapsed")
    if inspection["result"] != "PASS":
        violations.append("pdf_inspection")
    if memory["result"] != "PASS":
        violations.append("memory")

    evidence = {
        "schema_version": "sc-f2-label-font-ci-evidence-v1",
        "result": "PASS" if not violations else "FAIL",
        "execution_scope": "ARCHITECTURE_HOST_CONTAINER_CI_REHEARSAL",
        "ci_environment_variable": os.environ["CI"],
        "environment": environment,
        "controlled_scripts": scripts,
        "candidate": {
            "manifest_sha256": verifier["manifest_sha256"],
            "bundle_digest": verifier["bundle_digest"],
            "corpus_codepoints": verifier["corpus"]["positive_codepoints_count"],
        },
        "two_page_probe": two_page,
        "hundred_page_probe": hundred_page,
        "pdf_inspection": inspection["checks"],
        "memory_probe": memory,
        "violations": violations,
    }
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    if violations:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

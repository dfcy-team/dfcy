import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath


FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".pfx", ".crt", ".cer"}
RPA_RUNTIME_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".zip", ".crdownload", ".part"}
TEXT_SUFFIXES = {
    ".cfg",
    ".conf",
    ".env",
    ".ini",
    ".js",
    ".json",
    ".py",
    ".toml",
    ".ts",
    ".yaml",
    ".yml",
}
PLACEHOLDER_MARKERS = {
    "***",
    "change-me",
    "demo",
    "example",
    "not-a-real",
    "placeholder",
    "test",
    "${",
}
HIGH_CONFIDENCE_PATTERNS = {
    "private-key-header": re.compile("-----BEGIN " + "(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws-access-key": re.compile("AKI" + "A[0-9A-Z]{16}"),
    "github-token": re.compile("gh" + "[pousr]_[A-Za-z0-9]{30,}"),
    "openai-style-key": re.compile("sk" + "-[A-Za-z0-9_-]{20,}"),
}
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:[a-z0-9]+[_-])*(password|token|api[_-]?key|api[_-]?secret|secret[_-]?key)\b"
    r"\s*[:=]\s*([\"']?)([^\"'\s,#]+)"
)


def repository_files(root):
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def is_rpa_runtime_artifact(path):
    parts = path.parts
    if "rpa-agent" not in parts:
        return False
    if path.name == ".gitkeep":
        return False
    if "logs" in parts or "screenshots" in parts or "downloads" in parts:
        return True
    return path.suffix.lower() in RPA_RUNTIME_SUFFIXES


def scan_file(path, relative_path):
    findings = []
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return findings

    for line_number, line in enumerate(content.splitlines(), start=1):
        for rule_name, pattern in HIGH_CONFIDENCE_PATTERNS.items():
            if pattern.search(line):
                findings.append((rule_name, relative_path, line_number))

        if path.suffix.lower() not in TEXT_SUFFIXES or path.suffix.lower() == ".md":
            continue
        for match in ASSIGNMENT_PATTERN.finditer(line):
            quote, value = match.group(2), match.group(3)
            if not quote and path.suffix.lower() in {".py", ".js", ".ts"}:
                continue
            normalized_value = value.lower()
            if not any(marker in normalized_value for marker in PLACEHOLDER_MARKERS):
                findings.append(("credential-like-literal", relative_path, line_number))
    return findings


def run_guard(root):
    findings = []
    for tracked_name in repository_files(root):
        relative_path = PurePosixPath(tracked_name)
        path = root / Path(tracked_name)

        if relative_path.name == ".env":
            findings.append(("committed-dotenv", tracked_name, 0))
        if relative_path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(("private-or-database-artifact", tracked_name, 0))
        if is_rpa_runtime_artifact(relative_path):
            findings.append(("rpa-runtime-artifact", tracked_name, 0))
        if path.is_file():
            findings.extend(scan_file(path, tracked_name))

    if findings:
        print("CI guard failed. Suspected values are intentionally not displayed.")
        for rule_name, file_name, line_number in findings:
            location = f"{file_name}:{line_number}" if line_number else file_name
            print(f"- {rule_name}: {location}")
        return 1

    print("CI guard passed: no forbidden files or high-confidence credential patterns found.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Fail CI on forbidden artifacts or likely committed credentials.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    return run_guard(root)


if __name__ == "__main__":
    sys.exit(main())

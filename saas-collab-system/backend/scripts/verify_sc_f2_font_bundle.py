import argparse
import hashlib
import json
import pathlib
import unicodedata

from fontTools import version as fonttools_version
from fontTools.ttLib import TTFont


MANIFEST_SCHEMA = "sc-f2-label-font-candidate-manifest-v2"
DIGEST_SCHEMA = "sc-f2-label-font-bundle-digest-v1"


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_strict_json(path):
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_keys,
    )


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def font_names(font, name_id):
    return sorted(
        {record.toUnicode() for record in font["name"].names if record.nameID == name_id}
    )


def safe_bundle_path(bundle_dir, relative_path):
    candidate = pathlib.PurePosixPath(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in relative_path:
        raise ValueError(f"Unsafe bundle path: {relative_path!r}")
    resolved = (bundle_dir / pathlib.Path(*candidate.parts)).resolve()
    if resolved.parent != bundle_dir.resolve():
        raise ValueError(f"Bundle path escapes root: {relative_path!r}")
    return resolved


def canonical_digest_payload(manifest):
    records = [
        {
            "path": manifest["license"]["file"],
            "bytes": manifest["license"]["bytes"],
            "sha256": manifest["license"]["sha256"],
        }
    ]
    records.extend(
        {
            "path": asset["path"],
            "bytes": asset["bytes"],
            "sha256": asset["sha256"],
        }
        for asset in manifest["assets"]
    )
    return {
        "schema_version": DIGEST_SCHEMA,
        "assets": sorted(records, key=lambda item: item["path"]),
    }


def canonical_json_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def validate_corpus(corpus_path):
    raw = corpus_path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r\n" in raw:
        raise ValueError("Corpus must be UTF-8 without BOM and use LF line endings.")
    corpus = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    codepoints = [int(item[2:], 16) for item in corpus["positive_codepoints"]]
    if codepoints != sorted(set(codepoints)):
        raise ValueError("Corpus positive code points are not unique and sorted.")
    canonical = "".join(
        f"U+{item:04X}\n" if item <= 0xFFFF else f"U+{item:06X}\n"
        for item in codepoints
    ).encode("ascii")
    if hashlib.sha256(canonical).hexdigest() != corpus["positive_codepoints_sha256"]:
        raise ValueError("Corpus positive code point digest mismatch.")
    sample_codepoints = sorted(
        {
            ord(character)
            for sample in corpus["positive_samples"]
            for character in unicodedata.normalize("NFC", sample["text"])
        }
    )
    if sample_codepoints != codepoints:
        raise ValueError("Corpus positive samples do not reconstruct the frozen list.")
    for case in corpus["normalization_cases"]:
        if unicodedata.normalize("NFC", case["input"]) != case["normalized"]:
            raise ValueError(f"Normalization case failed: {case['id']}")
    return {
        "schema_version": corpus["schema_version"],
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "positive_codepoints_count": len(codepoints),
        "positive_codepoints_sha256": hashlib.sha256(canonical).hexdigest(),
        "codepoints": codepoints,
        "normalization_cases": len(corpus["normalization_cases"]),
        "negative_samples": len(corpus["negative_samples"]),
    }


def validate_font(path, asset, codepoints):
    if path.stat().st_size != asset["bytes"] or sha256(path) != asset["sha256"]:
        raise ValueError(f"Font bytes or SHA-256 mismatch: {asset['path']}")
    font = TTFont(
        path,
        lazy=False,
        recalcBBoxes=False,
        recalcTimestamp=False,
        checkChecksums=2,
    )
    try:
        for tag in font.keys():
            if tag != "GlyphOrder":
                font.getTableData(tag)
        variable_tables = sorted(
            set(font.keys()) & {"fvar", "gvar", "avar", "HVAR", "MVAR"}
        )
        cmap = font.getBestCmap() or {}
        missing = [item for item in codepoints if item not in cmap]
        actual = {
            "family": font_names(font, 1),
            "subfamily": font_names(font, 2),
            "full_name": font_names(font, 4),
            "font_version": font_names(font, 5),
            "postscript_name": font_names(font, 6),
            "typographic_family": font_names(font, 16),
            "typographic_subfamily": font_names(font, 17),
            "weight_class": int(font["OS/2"].usWeightClass),
            "width_class": int(font["OS/2"].usWidthClass),
            "fs_type": int(font["OS/2"].fsType),
            "variable_tables": variable_tables,
            "missing_codepoints": missing,
        }
        expected = {
            "family": [asset["family"]],
            "subfamily": [asset["subfamily"]],
            "full_name": [asset["full_name"]],
            "font_version": [asset["font_version"]],
            "postscript_name": [asset["postscript_name"]],
            "typographic_family": [asset["family"]],
            "typographic_subfamily": [asset["subfamily"]],
            "weight_class": asset["weight_class"],
            "width_class": asset["width_class"],
            "fs_type": asset["embedding"]["fs_type"],
            "variable_tables": [],
            "missing_codepoints": [],
        }
        if actual != expected:
            raise ValueError(
                f"Font metadata mismatch: {asset['path']}: "
                f"{json.dumps(actual, ensure_ascii=False, sort_keys=True)}"
            )
        if asset["embedding"]["rights"] != "INSTALLABLE_EMBEDDING":
            raise ValueError(f"Unexpected embedding rights: {asset['path']}")
        if asset["embedding"]["no_subsetting"]:
            raise ValueError(f"Subsetting is prohibited: {asset['path']}")
        return {
            "path": asset["path"],
            "bytes": asset["bytes"],
            "sha256": asset["sha256"],
            "glyph_count": int(font["maxp"].numGlyphs),
            "cmap_codepoints": len(cmap),
            "coverage_missing": 0,
        }
    finally:
        font.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", required=True, type=pathlib.Path)
    parser.add_argument("--corpus", required=True, type=pathlib.Path)
    args = parser.parse_args()

    bundle_dir = args.bundle_dir.resolve()
    manifest_path = bundle_dir / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Candidate manifest must not be a symbolic link.")
    manifest = load_strict_json(manifest_path)
    if manifest["schema_version"] != MANIFEST_SCHEMA:
        raise ValueError("Candidate manifest schema mismatch.")
    if manifest["coverage"]["tool"]["fonttools_version"] != fonttools_version:
        raise ValueError("fontTools version does not match candidate manifest.")
    corpus = validate_corpus(args.corpus)
    for key in (
        "schema_version",
        "file_sha256",
        "positive_codepoints_count",
        "positive_codepoints_sha256",
    ):
        if manifest["coverage"]["corpus"][key] != corpus[key]:
            raise ValueError(f"Manifest corpus field mismatch: {key}")

    asset_paths = [asset["path"] for asset in manifest["assets"]]
    if len(asset_paths) != len(set(asset_paths)):
        raise ValueError("Candidate manifest contains duplicate asset paths.")
    if {asset["role"] for asset in manifest["assets"]} != {"regular", "bold"}:
        raise ValueError("Candidate manifest must contain regular and bold roles.")
    expected_files = {"manifest.json", manifest["license"]["file"], *asset_paths}
    entries = list(bundle_dir.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise ValueError("Candidate bundle must not contain symbolic links.")
    if any(path.is_dir() for path in entries):
        raise ValueError("Candidate bundle must contain only root-level files.")
    actual_files = {
        path.relative_to(bundle_dir).as_posix()
        for path in entries
        if path.is_file()
    }
    if actual_files != expected_files:
        raise ValueError(
            f"Bundle file set mismatch: expected={sorted(expected_files)}, "
            f"actual={sorted(actual_files)}"
        )

    license_path = safe_bundle_path(bundle_dir, manifest["license"]["file"])
    if (
        license_path.stat().st_size != manifest["license"]["bytes"]
        or sha256(license_path) != manifest["license"]["sha256"]
    ):
        raise ValueError("License bytes or SHA-256 mismatch.")
    if b"Reserved Font Name 'Source'" not in license_path.read_bytes():
        raise ValueError("Reserved Font Name declaration is missing.")

    fonts = [
        validate_font(
            safe_bundle_path(bundle_dir, asset["path"]),
            asset,
            corpus["codepoints"],
        )
        for asset in manifest["assets"]
    ]
    payload = canonical_digest_payload(manifest)
    payload_bytes = canonical_json_bytes(payload)
    bundle_digest = hashlib.sha256(payload_bytes).hexdigest()
    if manifest["bundle_digest"]["schema_version"] != DIGEST_SCHEMA:
        raise ValueError("Bundle digest schema mismatch.")
    if manifest["bundle_digest"]["sha256"] != bundle_digest:
        raise ValueError("Bundle digest mismatch.")
    if manifest["authorization"]["renderer_versions"] or manifest["authorization"][
        "layout_versions"
    ]:
        raise ValueError("Candidate manifest must not pre-authorize renderer/layout.")
    if manifest["authorization"]["state"] != "BLOCKED_PENDING_R3_RECHECK_AND_R1_P2_002":
        raise ValueError("Candidate authorization state mismatch.")

    print(
        json.dumps(
            {
                "result": "PASS",
                "manifest_schema": MANIFEST_SCHEMA,
                "manifest_sha256": sha256(manifest_path),
                "fonttools_version": fonttools_version,
                "corpus": {key: value for key, value in corpus.items() if key != "codepoints"},
                "fonts": fonts,
                "bundle_digest": bundle_digest,
                "canonical_payload_utf8_sha256": hashlib.sha256(
                    payload_bytes
                ).hexdigest(),
                "authorization": manifest["authorization"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

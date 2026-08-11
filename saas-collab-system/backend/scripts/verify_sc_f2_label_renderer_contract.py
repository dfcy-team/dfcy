import argparse
import ast
import hashlib
import json
import pathlib
import unicodedata


SCHEMA = "sc-f2-label-renderer-contract-v1"
ALLOWED_STATES = {
    "FROZEN_PENDING_INDEPENDENT_REVIEW",
    "AUTHORIZED_FOR_SC_F2_LABEL_FONT_4_LOCAL_IMPLEMENTATION",
}


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_json(path):
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


def safe_path(root, relative):
    candidate = pathlib.PurePosixPath(relative)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in relative:
        raise ValueError(f"Unsafe repository path: {relative!r}")
    resolved = (root / pathlib.Path(*candidate.parts)).resolve()
    if root.resolve() not in resolved.parents:
        raise ValueError(f"Repository path escapes root: {relative!r}")
    return resolved


def class_string_constants(path, class_name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            values = {}
            for statement in node.body:
                if (
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)
                ):
                    values[statement.targets[0].id] = statement.value.value
            return values
    raise ValueError(f"Class {class_name!r} was not found in {path}.")


def module_string_constants(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = {}
    for statement in tree.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            values[statement.targets[0].id] = statement.value.value
    return values


def in_ranges(codepoint, ranges):
    return any(
        int(record["start"][2:], 16) <= codepoint <= int(record["end"][2:], 16)
        for record in ranges
    )


def is_allowed(codepoint, policy):
    return in_ranges(codepoint, policy["allowed_ranges"]) or codepoint in {
        int(item[2:], 16) for item in policy["allowed_codepoints"]
    }


def classify_character(character, policy):
    codepoint = ord(character)
    if unicodedata.category(character) == "Cc":
        return "CONTROL_CHARACTER_FORBIDDEN"
    if codepoint in {int(item[2:], 16) for item in policy["zero_width_codepoints"]}:
        return "ZERO_WIDTH_CHARACTER_FORBIDDEN"
    if any(
        int(record["start"][2:], 16) <= codepoint <= int(record["end"][2:], 16)
        for record in policy["variation_selector_ranges"]
    ):
        return "VARIATION_SELECTOR_FORBIDDEN"
    if unicodedata.category(character) == "Co":
        return "PRIVATE_USE_CHARACTER_FORBIDDEN"
    if unicodedata.category(character) == "Cf":
        return "FORMAT_CHARACTER_FORBIDDEN"
    if unicodedata.category(character) in {"Cs", "Cn"}:
        return "UNASSIGNED_OR_SURROGATE_FORBIDDEN"
    if any(
        int(record["start"][2:], 16) <= codepoint <= int(record["end"][2:], 16)
        for record in policy["emoji_ranges"]
    ):
        return "EMOJI_FORBIDDEN"
    if unicodedata.category(character) in {"Mn", "Mc", "Me"}:
        return "COMBINING_MARK_OUT_OF_SCOPE"
    if unicodedata.category(character).startswith("Z") and codepoint != 0x20:
        return "NON_ASCII_SEPARATOR_FORBIDDEN"
    if not is_allowed(codepoint, policy):
        return "OUT_OF_FROZEN_CJK_SCOPE"
    return None


def verify(root, contract_path):
    root = root.resolve()
    contract = load_json(contract_path)
    if contract["schema_version"] != SCHEMA:
        raise ValueError("Renderer contract schema mismatch.")
    if contract["gate"]["state"] not in ALLOWED_STATES:
        raise ValueError("Renderer contract gate state is invalid.")
    if contract["gate"]["state"].startswith("AUTHORIZED") and not contract["gate"].get(
        "closed_by_review"
    ):
        raise ValueError("Authorized contract is missing its independent review ID.")

    verifier = safe_path(root, contract["controlled_verifier"]["path"])
    if sha256(verifier) != contract["controlled_verifier"]["sha256"]:
        raise ValueError("Controlled renderer contract verifier hash mismatch.")

    error_codes_path = safe_path(root, contract["source_contracts"]["error_codes"])
    actual_codes = set(class_string_constants(error_codes_path, "ErrorCode").values())
    public_errors = contract["public_errors"]
    expected_errors = {
        "UNSUPPORTED_TEXT": (
            422,
            "BUSINESS_RULE_VIOLATION",
            "Label content contains unsupported characters.",
        ),
        "LAYOUT_LIMIT_EXCEEDED": (
            422,
            "BUSINESS_RULE_VIOLATION",
            "Label content exceeds the supported layout limits.",
        ),
        "RENDERER_UNAVAILABLE": (
            500,
            "INTERNAL_ERROR",
            "Label rendering is temporarily unavailable.",
        ),
    }
    if set(public_errors) != set(expected_errors):
        raise ValueError("Public renderer error set mismatch.")
    for name, expected in expected_errors.items():
        record = public_errors[name]
        actual = (record["http_status"], record["code"], record["message"])
        if actual != expected:
            raise ValueError(f"Public renderer error mismatch: {name}")
        if record["code"] not in actual_codes:
            raise ValueError(f"Renderer error code is absent from ErrorCode: {name}")
        if record["data"] is not None or record["content_type"] != "application/json":
            raise ValueError(f"Renderer error envelope is unsafe: {name}")

    forbidden_tokens = [item.lower() for item in contract["response_safety"]["forbidden_tokens"]]
    for record in public_errors.values():
        message = record["message"].lower()
        if any(token in message for token in forbidden_tokens):
            raise ValueError("Public renderer message contains a forbidden token.")
        if record["forbidden_response_headers"] != [
            "Content-Disposition",
            "ETag",
            "Idempotency-Replayed",
            "X-Packing-Batch-Version",
        ]:
            raise ValueError("Renderer failure header contract mismatch.")

    corpus_path = safe_path(root, contract["unicode_policy"]["corpus"]["path"])
    corpus = load_json(corpus_path)
    corpus_contract = contract["unicode_policy"]["corpus"]
    if sha256(corpus_path) != corpus_contract["sha256"]:
        raise ValueError("Renderer corpus file hash mismatch.")
    if corpus["positive_codepoints_sha256"] != corpus_contract[
        "positive_codepoints_sha256"
    ]:
        raise ValueError("Renderer corpus code point hash mismatch.")
    if corpus["positive_codepoints_count"] != corpus_contract["positive_codepoints_count"]:
        raise ValueError("Renderer corpus code point count mismatch.")

    policy = contract["unicode_policy"]
    for case in corpus["normalization_cases"]:
        if unicodedata.normalize("NFC", case["input"]) != case["normalized"]:
            raise ValueError(f"NFC case failed: {case['id']}")
    for item in corpus["positive_codepoints"]:
        character = chr(int(item[2:], 16))
        if classify_character(character, policy) is not None:
            raise ValueError(f"Positive code point is rejected by policy: {item}")
    for sample in corpus["negative_samples"]:
        normalized = unicodedata.normalize("NFC", sample["text"])
        reasons = [classify_character(character, policy) for character in normalized]
        reasons = [reason for reason in reasons if reason]
        if reasons != [sample["expected_reason"]]:
            raise ValueError(f"Negative sample reason mismatch: {sample['id']}")

    candidate_codepoints = {
        int(item[2:], 16) for item in policy["allowed_codepoints"]
    }
    for record in policy["allowed_ranges"]:
        candidate_codepoints.update(
            range(
                int(record["start"][2:], 16),
                int(record["end"][2:], 16) + 1,
            )
        )
    accepted_codepoints = sorted(
        codepoint
        for codepoint in candidate_codepoints
        if classify_character(chr(codepoint), policy) is None
    )
    canonical_scope = "".join(
        f"U+{codepoint:04X}\n"
        if codepoint <= 0xFFFF
        else f"U+{codepoint:06X}\n"
        for codepoint in accepted_codepoints
    ).encode("ascii")
    frozen_scope = policy["frozen_accepted_scope"]
    if len(accepted_codepoints) != frozen_scope["codepoints_count"]:
        raise ValueError("Frozen renderer character scope count mismatch.")
    if len(canonical_scope) != frozen_scope["canonical_bytes"]:
        raise ValueError("Frozen renderer character scope byte count mismatch.")
    if hashlib.sha256(canonical_scope).hexdigest() != frozen_scope["sha256"]:
        raise ValueError("Frozen renderer character scope digest mismatch.")

    bundle = contract["asset_bundle"]
    bundle_dir = safe_path(root, bundle["repository_path"])
    expected_files = {record["path"] for record in bundle["files"]}
    actual_files = {path.name for path in bundle_dir.iterdir() if path.is_file()}
    if actual_files != expected_files:
        raise ValueError("Approved renderer asset file set mismatch.")
    for record in bundle["files"]:
        path = bundle_dir / record["path"]
        if path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
            raise ValueError(f"Approved renderer asset drift: {record['path']}")

    labels_path = safe_path(root, contract["source_contracts"]["v1_renderer"])
    constants = module_string_constants(labels_path)
    expected_v1 = contract["version_dispatch"]["preserved_v1"]
    if constants.get("LAYOUT_VERSION") != expected_v1["layout_version"]:
        raise ValueError("Existing v1 layout version drifted.")
    if constants.get("RENDERER_VERSION") != expected_v1["renderer_version"]:
        raise ValueError("Existing v1 renderer version drifted.")

    if contract["idempotency_and_transactions"] != {
        "first_user_text_failure": "ROLLBACK_ALL_AND_STORE_NO_IDEMPOTENCY_RECORD",
        "first_asset_or_renderer_failure": "ROLLBACK_ALL_AND_STORE_NO_IDEMPOTENCY_RECORD",
        "same_key_after_user_input_fix": "ALLOWED_AS_FRESH_REQUEST_BECAUSE_NO_RECORD_EXISTS",
        "same_key_after_asset_repair": "ALLOWED_WITH_IDENTICAL_REQUEST_BECAUSE_NO_RECORD_EXISTS",
        "historical_replay_failure": "RETURN_SAFE_500_WITH_ZERO_WRITES_AND_PRESERVE_RECORD",
        "historical_replay_after_repair": "RENDER_FROZEN_SNAPSHOT_AND_RETURN_ORIGINAL_BYTES_ETAG",
        "authorization_before_replay": True,
        "store_failed_response": False,
        "pdf_bytes_in_database": False,
        "first_real_render_before_outer_commit": True,
    }:
        raise ValueError("Renderer transaction/idempotency contract mismatch.")

    result = {
        "result": "PASS",
        "schema_version": SCHEMA,
        "gate_state": contract["gate"]["state"],
        "contract_sha256": sha256(contract_path),
        "verifier_sha256": sha256(verifier),
        "asset_bundle_digest": bundle["bundle_digest_sha256"],
        "positive_codepoints": corpus["positive_codepoints_count"],
        "accepted_scope_codepoints": len(accepted_codepoints),
        "negative_samples": len(corpus["negative_samples"]),
        "public_errors": sorted(public_errors),
        "v1_preserved": True,
        "renderer_code_changed": False,
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=pathlib.Path)
    parser.add_argument("--contract", required=True, type=pathlib.Path)
    args = parser.parse_args()
    result = verify(args.root, args.contract.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

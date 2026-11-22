import importlib.util
from pathlib import Path
import pytest

CI = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("docker_check", CI / "v518_docker_input_check.py")
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


def fixture(tmp_path, dockerfile, files=(), ignore=""):
    (tmp_path / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    (tmp_path / ".dockerignore").write_text(ignore, encoding="utf-8")
    for name in files:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("ok", encoding="utf-8")
    return tmp_path


def run(root):
    return check.check_recipe(root, "Dockerfile", ".")


def test_fails_old_bad_0051_missing_copy(tmp_path):
    root = fixture(tmp_path, "FROM node\nCOPY backend/apps/influencers/0051_requirement_images.py /app/x\n")
    assert any("source missing" in e for e in run(root))


def test_passes_correct_0049_fixture(tmp_path):
    root = fixture(tmp_path, "FROM node\nCOPY backend/apps/influencers/0049_requirement_images.py /app/x\n", ["backend/apps/influencers/0049_requirement_images.py"])
    assert run(root) == []


def test_comment_continuation_does_not_hide_missing_copy(tmp_path):
    root = fixture(tmp_path, "FROM node\n# comment \\\nCOPY missing /out\n")
    assert any("source missing" in e for e in run(root))


def test_blank_and_comment_preserve_pending_continuation(tmp_path):
    root = fixture(tmp_path, "FROM node\nCOPY \\\n\n# comment \\\na.txt /out\n", ["a.txt"])
    assert run(root) == []


def test_nondefault_escape_directive_rejected(tmp_path):
    root = fixture(tmp_path, "# escape=`\nFROM node\n")
    with pytest.raises(ValueError, match="unsupported parser escape"):
        list(check.instructions(root / "Dockerfile"))


def test_multiline_json_and_from_stage(tmp_path):
    root = fixture(tmp_path, 'FROM node AS build\nCOPY \\\n ["a.txt", "b.txt", "/app/"]\nFROM nginx\nCOPY --from=build /app/out /site\n', ["a.txt", "b.txt"])
    assert run(root) == []


def test_empty_glob_traversal_and_ignore_fail(tmp_path):
    root = fixture(tmp_path, "COPY missing*.txt /x\nCOPY ../outside /x\nCOPY secret.txt /x\n", ["secret.txt"], "secret.txt\n")
    errors = run(root)
    assert len(errors) == 3
    assert any("glob empty" in e for e in errors)
    assert any("escapes" in e for e in errors)
    assert any("excluded" in e for e in errors)


def test_symlink_escape_and_unproven_stage_fail(tmp_path):
    outside = tmp_path.parent / "external-docker-input"
    outside.write_text("x", encoding="utf-8")
    (tmp_path / "linked").symlink_to(outside)
    root = fixture(tmp_path, "COPY linked /x\nCOPY --from=remote /x /y\n")
    errors = run(root)
    assert any("symlink target" in e for e in errors)
    assert any("not declared earlier" in e for e in errors)


def test_local_stage_requires_prior_from_and_multiple_sources_with_flags(tmp_path):
    root = fixture(tmp_path, "FROM node AS build\nCOPY --chown=1000:1000 a.txt b.txt /dest/\nFROM nginx\nCOPY --from=build /out /site\nCOPY --from=later /out /bad\nFROM node AS later\n", ["a.txt", "b.txt"])
    errors = run(root)
    assert len(errors) == 1
    assert "not declared earlier" in errors[0]


@pytest.mark.parametrize("stage", ["build", "0"])
def test_current_stage_is_not_a_valid_copy_source(tmp_path, stage):
    root = fixture(tmp_path, f"FROM node AS build\nCOPY --from={stage} /out /site\n")
    assert any("not declared earlier" in e for e in run(root))


def test_context_specific_ignore_is_used(tmp_path):
    context = tmp_path / "backend"
    context.mkdir()
    fixture(context, "FROM python\nCOPY requirements.txt /app/\n", ["requirements.txt"], "requirements.txt\n")
    assert any("excluded" in e for e in check.check_recipe(tmp_path, "backend/Dockerfile", "backend"))


def test_recipe_specific_ignore_overrides_context_ignore(tmp_path):
    root = fixture(tmp_path, "FROM node\nCOPY a.txt /app/\n", ["a.txt"], "a.txt\n")
    (root / "Dockerfile.dockerignore").write_text("not-a.txt\n", encoding="utf-8")
    assert run(root) == []


@pytest.mark.parametrize("instruction", [
    "COPY $UNBOUND /app/", "COPY --exclude=*.txt a.txt /app/",
    'COPY ["", "/app/"]', "COPY /outside /app/", "COPY missing*.txt /app/",
])
def test_unsupported_or_unresolved_input_fails_closed(tmp_path, instruction):
    root = fixture(tmp_path, "FROM node\n" + instruction + "\n", ["a.txt"])
    assert run(root)


def test_context_cannot_be_a_symlink_outside_source(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside-context")
    outside.mkdir()
    (tmp_path / "backend").symlink_to(outside, target_is_directory=True)
    (tmp_path / "Dockerfile").write_text("COPY . /app\n", encoding="utf-8")
    assert any("escapes reviewed" in e for e in check.check_recipe(tmp_path, "Dockerfile", "backend"))


def test_ignored_directory_trailing_slash_blocks_child(tmp_path):
    root = fixture(tmp_path, "COPY private/file.txt /app/\n", ["private/file.txt"], "private/\n")
    assert any("excluded" in e for e in run(root))


def test_duplicate_stage_flag_and_stage_variable_fail_closed(tmp_path):
    root = fixture(tmp_path, "FROM node AS build\nFROM nginx\nCOPY --from=build --from=external /out /site\n")
    assert any("duplicate" in e for e in run(root))
    (root / "Dockerfile").write_text("FROM node AS build\nFROM nginx\nCOPY --from=build $UNKNOWN /site\n", encoding="utf-8")
    assert any("unresolved source variable" in e for e in run(root))


def test_workflow_input_gate_precedes_long_jobs_and_publication():
    import yaml
    root = CI.parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/v518-cloud-artifacts-build-only.yml").read_text(encoding="utf-8"))
    script = next(s["run"] for s in workflow["jobs"]["validate"]["steps"] if "v518_docker_input_check.py" in s.get("run", ""))
    assert script.index("v518_docker_input_check.py") < script.index("v518_cloud_build_only.py validate")
    for name, job in workflow["jobs"].items():
        if name != "validate": assert "validate" in ([job["needs"]] if isinstance(job["needs"], str) else job["needs"])

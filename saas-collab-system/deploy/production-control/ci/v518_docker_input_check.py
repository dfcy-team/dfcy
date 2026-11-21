"""Fail-closed, dependency-free validation of local Docker build inputs."""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

RECIPES = {
    "backend/Dockerfile": "backend",
    "deploy/pilot/application/Dockerfile.frontend": ".",
    "deploy/sandbox/application/Dockerfile.frontend": ".",
    "deploy/dev-sandbox/Dockerfile.frontend.dev": ".",
    "deploy/dev-sandbox/Dockerfile.backend.dev": ".",
}
CONTINUATION = re.compile(r"\\\s*$")
VAR = re.compile(r"\$(?:\{[^}]*\}|[A-Za-z_][A-Za-z0-9_]*)")


def instructions(path: Path):
    logical = ""
    start = 0
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if re.match(r"#\s*escape\s*=", line, re.IGNORECASE):
            raise ValueError(f"{path.name}:{number}: unsupported parser escape directive")
        if not line or line.startswith("#"):
            continue
        if not logical:
            start = number
        logical += (" " if logical else "") + line
        if CONTINUATION.search(logical):
            logical = CONTINUATION.sub("", logical).rstrip()
            continue
        if logical and not logical.startswith("#"):
            yield start, logical
        logical = ""
    if logical:
        raise ValueError(f"{path.name}:{start}: unterminated continuation")


def copy_sources(rest: str):
    rest = rest.strip()
    flags = []
    while rest.startswith("--"):
        flag, _, rest = rest.partition(" ")
        if not (flag.startswith(("--from=", "--chown=", "--chmod=")) or flag == "--link"):
            raise ValueError("unsupported COPY/ADD flag")
        flags.append(flag)
        rest = rest.lstrip()
    keys = [flag.split("=", 1)[0] for flag in flags]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate COPY/ADD flag")
    if rest.startswith("["):
        try:
            values = json.loads(rest)
        except json.JSONDecodeError as e:
            raise ValueError("unsupported COPY/ADD JSON form") from e
        if not isinstance(values, list) or len(values) < 2 or not all(isinstance(v, str) and v for v in values):
            raise ValueError("unsupported COPY/ADD JSON form")
        return values[:-1], flags
    # Shell form: Docker source paths are whitespace-separated; quoted spaces are unsupported.
    if '"' in rest or "'" in rest or "`" in rest:
        raise ValueError("quoted COPY/ADD paths are unsupported")
    fields = rest.split()
    if len(fields) < 2:
        raise ValueError("COPY/ADD requires a source and destination")
    return fields[:-1], flags


def dockerignore_patterns(root: Path, p=None):
    p = root / ".dockerignore" if p is None else p
    if not p.exists():
        return []
    if not p.resolve().is_relative_to(root.resolve()):
        raise ValueError("ignore file escapes reviewed source root")
    patterns = []
    for n, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith("#") or s == ".":
            continue
        if s.startswith("!") or "\\" in s:
            raise ValueError(f".dockerignore:{n}: negation/escape patterns unsupported")
        patterns.append(s.strip("/"))
    return patterns


def ignored(rel: str, patterns):
    parts = rel.split("/")
    for pat in patterns:
        if fnmatch.fnmatchcase(rel, pat) or fnmatch.fnmatchcase(rel, "**/" + pat):
            return True
        if any(fnmatch.fnmatchcase("/".join(parts[:i]), pat) for i in range(1, len(parts))):
            return True
    return False


def check_recipe(source_root: Path, recipe_rel: str, context_rel: str):
    errors = []
    recipe = source_root / recipe_rel
    context = (source_root / context_rel).resolve()
    if not recipe.is_file():
        return [f"{recipe_rel}: recipe missing"]
    if not context.is_relative_to(source_root.resolve()) or not recipe.resolve().is_relative_to(source_root.resolve()):
        return [f"{recipe_rel}: recipe or context escapes reviewed source root"]
    try:
        specific_ignore = recipe.with_name(recipe.name + ".dockerignore")
        ignore_path = specific_ignore if specific_ignore.exists() else context / ".dockerignore"
        patterns = dockerignore_patterns(source_root, ignore_path)
        local_stages = set()
        current_stages = set()
        stage_number = 0
        for line, text in instructions(recipe):
            stage = re.match(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", text, re.I)
            if stage:
                local_stages.update(current_stages)
                current_stages = {str(stage_number)}
                image = stage.group(1)
                if VAR.search(image):
                    raise ValueError(f"{recipe_rel}:{line}: unresolved FROM image")
                if stage.group(2):
                    if stage.group(2) in local_stages:
                        raise ValueError(f"{recipe_rel}:{line}: duplicate stage alias")
                    current_stages.add(stage.group(2))
                stage_number += 1
                continue
            match = re.match(r"^(COPY|ADD)\s+(.+)$", text, re.I)
            if not match:
                continue
            sources, flags = copy_sources(match.group(2))
            if any(VAR.search(source) for source in sources):
                raise ValueError(f"{recipe_rel}:{line}: unresolved source variable")
            from_flag = next((x for x in flags if x.startswith("--from=")), None)
            if from_flag:
                stage = from_flag.split("=", 1)[1]
                if stage not in local_stages:
                    errors.append(f"{recipe_rel}:{line}: COPY/ADD stage not declared earlier in this recipe")
                continue
            for source in sources:
                if source == ".":
                    candidates = [context]
                else:
                    if VAR.search(source):
                        errors.append(f"{recipe_rel}:{line}: unresolved source variable")
                        continue
                    if Path(source).is_absolute() or ".." in Path(source).parts:
                        errors.append(f"{recipe_rel}:{line}: source escapes context")
                        continue
                    candidate = context / source
                    if "**" in source:
                        matches = list(context.glob(source))
                    elif any(c in source for c in "*?["):
                        matches = list(context.glob(source))
                    else:
                        matches = [candidate] if candidate.exists() else []
                    if not matches:
                        errors.append(f"{recipe_rel}:{line}: source missing or glob empty")
                        continue
                    candidates = matches
                for item in candidates:
                    resolved = item.resolve()
                    if not resolved.is_relative_to(context):
                        errors.append(f"{recipe_rel}:{line}: source escapes context or symlink target")
                        continue
                    rel = resolved.relative_to(context).as_posix()
                    if ignored(rel, patterns):
                        errors.append(f"{recipe_rel}:{line}: source excluded by .dockerignore")
    except (OSError, ValueError) as e:
        errors.append(f"{recipe_rel}: {str(e).splitlines()[0]}")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    args = parser.parse_args(argv)
    root = args.source_root.resolve()
    errors = []
    for recipe, context in RECIPES.items():
        errors.extend(check_recipe(root, recipe, context))
    if errors:
        for error in errors[:30]:
            print(error, file=sys.stderr)
        print(f"Docker input preflight failed ({min(len(errors), 30)}/{len(errors)} shown)", file=sys.stderr)
        return 1
    print(f"Docker input preflight passed ({len(RECIPES)} recipes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate Lean CUDA release metadata and build the static distribution site."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from typing import Any, NoReturn


RELEASE_SCHEMA = "lean.cuda.release/v1"
MANIFEST_SCHEMA = "lean.cuda.release-manifest/v1"
INDEX_SCHEMA = "lean.cuda.release-index/v1"
LATEST_SCHEMA = "lean.cuda.latest/v1"
BUILD_STATUS_SCHEMA = "lean.cuda.build-status/v1"
DISTRIBUTION_REPOSITORY = "ranvier-labs/lean4-cuda-nightly"
MAX_RELEASE_ROWS = 3

ID_RE = re.compile(
    r"^nightly-(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"(?:-rev(?P<revision>[1-9][0-9]*))?$"
)
VERSION_RE = re.compile(
    r"^(?P<base>[0-9]+\.[0-9]+\.[0-9]+)-cuda-nightly\."
    r"(?P<date>[0-9]{8})(?:\.rev(?P<revision>[1-9][0-9]*))?\."
    r"g(?P<commit>[0-9a-f]{7,12})$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

ARCHITECTURES = {
    "x86_64": {
        "suffix": "linux",
        "sass": ["sm_90a", "sm_100a", "sm_120a"],
    },
    "aarch64": {
        "suffix": "linux_aarch64",
        "sass": ["sm_90a", "sm_100a", "sm_121a"],
    },
}

DEFAULT_LIMITATIONS = (
    "Experimental nightly APIs may change incompatibly.",
    "This release carries no H100 performance claim.",
)
CUDA_UPSTREAM_REPOSITORY = "ranvier-labs/lean4-cuda-backend"


class ContractError(Exception):
    """Public release metadata violates the distribution contract."""


def fail(path: str, message: str) -> NoReturn:
    raise ContractError(f"{path}: {message}")


def require(condition: bool, path: str, message: str) -> None:
    if not condition:
        fail(path, message)


def require_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(path, "must be a JSON object")
    return value


def require_array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        fail(path, "must be a JSON array")
    return value


def require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        fail(path, "must be a non-empty string")
    return value


def require_integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        fail(path, f"must be an integer >= {minimum}")
    return value


def require_exact_keys(
    value: dict[str, Any],
    path: str,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = sorted(required - value.keys())
    extra = sorted(value.keys() - required - optional)
    if missing:
        fail(path, "missing fields: " + ", ".join(missing))
    if extra:
        fail(path, "unknown fields: " + ", ".join(extra))


def require_sha256(value: Any, path: str) -> str:
    value = require_string(value, path)
    require(SHA256_RE.fullmatch(value) is not None, path, "must be a lowercase SHA-256")
    return value


def require_https(value: Any, path: str) -> str:
    value = require_string(value, path)
    require(value.startswith("https://"), path, "must use HTTPS")
    return value


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ContractError(f"{path}: cannot read file: {error}") from error
    except json.JSONDecodeError as error:
        raise ContractError(
            f"{path}:{error.lineno}:{error.colno}: invalid JSON: {error.msg}"
        ) from error


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_build_status(value: Any, origin: str = "build status") -> dict[str, Any]:
    status = require_object(value, origin)
    require_exact_keys(
        status,
        origin,
        required={
            "schema",
            "channel",
            "state",
            "releaseId",
            "startedAt",
            "updatedAt",
            "message",
        },
    )
    require(
        status["schema"] == BUILD_STATUS_SCHEMA,
        f"{origin}.schema",
        f"must be {BUILD_STATUS_SCHEMA!r}",
    )
    require(status["channel"] == "nightly", f"{origin}.channel", "must be 'nightly'")
    state = require_string(status["state"], f"{origin}.state")
    require(
        state in {"running", "accepted", "failed"},
        f"{origin}.state",
        "must be 'running', 'accepted', or 'failed'",
    )
    release_id = require_string(status["releaseId"], f"{origin}.releaseId")
    match = ID_RE.fullmatch(release_id)
    require(match is not None, f"{origin}.releaseId", "must be a nightly release id")
    assert match is not None
    try:
        date.fromisoformat(match.group("date"))
    except ValueError as error:
        fail(f"{origin}.releaseId", f"contains an invalid calendar date: {error}")
    parsed_times: dict[str, datetime] = {}
    for field in ("startedAt", "updatedAt"):
        timestamp = require_string(status[field], f"{origin}.{field}")
        require(timestamp.endswith("Z"), f"{origin}.{field}", "must be expressed in UTC with Z")
        try:
            parsed_times[field] = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as error:
            fail(f"{origin}.{field}", f"invalid RFC 3339 timestamp: {error}")
    require(
        parsed_times["updatedAt"] >= parsed_times["startedAt"],
        f"{origin}.updatedAt",
        "cannot precede startedAt",
    )
    require_string(status["message"], f"{origin}.message")
    return status

def build_status(
    *,
    state: str,
    release_id: str,
    started_at: str,
    updated_at: str,
    message: str,
) -> dict[str, Any]:
    return validate_build_status(
        {
            "schema": BUILD_STATUS_SCHEMA,
            "channel": "nightly",
            "state": state,
            "releaseId": release_id,
            "startedAt": started_at,
            "updatedAt": updated_at,
            "message": message,
        }
    )



def validate_release(value: Any, origin: str = "release") -> dict[str, Any]:
    record = require_object(value, origin)
    require_exact_keys(
        record,
        origin,
        required={
            "schema",
            "channel",
            "id",
            "version",
            "publishedAt",
            "source",
            "build",
            "gates",
            "contentPolicy",
            "installation",
            "artifacts",
            "limitations",
        },
    )
    require(record["schema"] == RELEASE_SCHEMA, f"{origin}.schema", f"must be {RELEASE_SCHEMA!r}")
    require(record["channel"] == "nightly", f"{origin}.channel", "must be 'nightly'")

    release_id = require_string(record["id"], f"{origin}.id")
    id_match = ID_RE.fullmatch(release_id)
    require(id_match is not None, f"{origin}.id", "must be nightly-YYYY-MM-DD or a -revN retry")
    assert id_match is not None
    try:
        release_date = date.fromisoformat(id_match.group("date"))
    except ValueError as error:
        fail(f"{origin}.id", f"contains an invalid calendar date: {error}")

    version = require_string(record["version"], f"{origin}.version")
    version_match = VERSION_RE.fullmatch(version)
    require(version_match is not None, f"{origin}.version", "does not match the nightly version format")
    assert version_match is not None
    require(
        version_match.group("date") == release_date.strftime("%Y%m%d"),
        f"{origin}.version",
        "date does not match release id",
    )
    require(
        version_match.group("revision") == id_match.group("revision"),
        f"{origin}.version",
        "revision does not match release id",
    )

    published_at = require_string(record["publishedAt"], f"{origin}.publishedAt")
    require(published_at.endswith("Z"), f"{origin}.publishedAt", "must be expressed in UTC with Z")
    try:
        parsed_published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError as error:
        fail(f"{origin}.publishedAt", f"invalid RFC 3339 timestamp: {error}")
    require(
        parsed_published_at.date() >= release_date,
        f"{origin}.publishedAt",
        "cannot precede the release date",
    )

    source = require_object(record["source"], f"{origin}.source")
    require_exact_keys(
        source,
        f"{origin}.source",
        required={"visibility", "commit"},
        optional={"tree"},
    )
    require(source["visibility"] == "private", f"{origin}.source.visibility", "must be 'private'")
    commit = require_string(source["commit"], f"{origin}.source.commit")
    require(COMMIT_RE.fullmatch(commit) is not None, f"{origin}.source.commit", "must be a full lowercase Git commit")
    if "tree" in source:
        tree = require_string(source["tree"], f"{origin}.source.tree")
        require(COMMIT_RE.fullmatch(tree) is not None, f"{origin}.source.tree", "must be a full lowercase Git tree")
    require(
        commit.startswith(version_match.group("commit")),
        f"{origin}.version",
        "short commit suffix does not match source.commit",
    )

    build = require_object(record["build"], f"{origin}.build")
    require_exact_keys(
        build,
        f"{origin}.build",
        required={"cudaToolkitVersion", "ptxArchitecture", "workflowUrl", "validation"},
    )
    cuda_version = require_string(build["cudaToolkitVersion"], f"{origin}.build.cudaToolkitVersion")
    require(re.fullmatch(r"13\.[0-9]+\.[0-9]+", cuda_version) is not None, f"{origin}.build.cudaToolkitVersion", "must be a CUDA 13 compiler version")
    ptx = require_string(build["ptxArchitecture"], f"{origin}.build.ptxArchitecture")
    require(re.fullmatch(r"compute_[0-9]+", ptx) is not None, f"{origin}.build.ptxArchitecture", "must be compute_NNN")
    require_https(build["workflowUrl"], f"{origin}.build.workflowUrl")

    validation = require_object(build["validation"], f"{origin}.build.validation")
    require_exact_keys(
        validation,
        f"{origin}.build.validation",
        required={"registered", "failures", "skipped", "umbrellaModules", "extractedSmoke"},
    )
    require_integer(validation["registered"], f"{origin}.build.validation.registered", minimum=1)
    failures = require_integer(validation["failures"], f"{origin}.build.validation.failures")
    require(failures == 0, f"{origin}.build.validation.failures", "must be zero")
    require_integer(validation["skipped"], f"{origin}.build.validation.skipped")
    require_integer(validation["umbrellaModules"], f"{origin}.build.validation.umbrellaModules", minimum=1)
    require(validation["extractedSmoke"] is True, f"{origin}.build.validation.extractedSmoke", "must be true")

    gates = require_object(record["gates"], f"{origin}.gates")
    require_exact_keys(
        gates,
        f"{origin}.gates",
        required={"dualArchitectureCI", "h100", "performanceClaims"},
        optional={"h100EvidenceUrl"},
    )
    require(gates["dualArchitectureCI"] == "passed", f"{origin}.gates.dualArchitectureCI", "must be 'passed'")
    h100 = gates["h100"]
    require(h100 in {"not-run", "passed"}, f"{origin}.gates.h100", "must be 'not-run' or 'passed'")
    require(type(gates["performanceClaims"]) is bool, f"{origin}.gates.performanceClaims", "must be a boolean")
    if h100 == "not-run":
        require(not gates["performanceClaims"], f"{origin}.gates.performanceClaims", "must be false without a passed H100 gate")
        require("h100EvidenceUrl" not in gates, f"{origin}.gates.h100EvidenceUrl", "must be absent when H100 was not run")
    if gates["performanceClaims"]:
        require(h100 == "passed", f"{origin}.gates.h100", "must be passed for performance claims")
    if h100 == "passed":
        require("h100EvidenceUrl" in gates, f"{origin}.gates", "passed H100 gate requires h100EvidenceUrl")
        require_https(gates["h100EvidenceUrl"], f"{origin}.gates.h100EvidenceUrl")

    policy = require_object(record["contentPolicy"], f"{origin}.contentPolicy")
    require_exact_keys(
        policy,
        f"{origin}.contentPolicy",
        required={"privateLeanSources", "sdkHeaders"},
    )
    require(policy["privateLeanSources"] == "excluded", f"{origin}.contentPolicy.privateLeanSources", "must be 'excluded'")
    require(policy["sdkHeaders"] == "included", f"{origin}.contentPolicy.sdkHeaders", "must be 'included'")

    installation = require_object(record["installation"], f"{origin}.installation")
    require_exact_keys(
        installation,
        f"{origin}.installation",
        required={"repository", "elanToolchain"},
    )
    repository = require_string(installation["repository"], f"{origin}.installation.repository")
    require(
        repository == DISTRIBUTION_REPOSITORY,
        f"{origin}.installation.repository",
        f"must be {DISTRIBUTION_REPOSITORY!r}",
    )
    expected_toolchain = f"{repository}:{release_id}"
    require(installation["elanToolchain"] == expected_toolchain, f"{origin}.installation.elanToolchain", f"must be {expected_toolchain!r}")

    artifacts = require_array(record["artifacts"], f"{origin}.artifacts")
    require(len(artifacts) == 2, f"{origin}.artifacts", "must contain exactly x86_64 and aarch64")
    seen_architectures: set[str] = set()
    release_base_url = f"https://github.com/{repository}/releases/download/{release_id}/"
    for index, raw_artifact in enumerate(artifacts):
        artifact_path = f"{origin}.artifacts[{index}]"
        artifact = require_object(raw_artifact, artifact_path)
        require_exact_keys(
            artifact,
            artifact_path,
            required={
                "hostSystem",
                "architecture",
                "name",
                "url",
                "checksumUrl",
                "sha256",
                "size",
                "sassArchitectures",
                "manifest",
            },
        )
        require(artifact["hostSystem"] == "Linux", f"{artifact_path}.hostSystem", "must be 'Linux'")
        architecture = require_string(artifact["architecture"], f"{artifact_path}.architecture")
        require(architecture in ARCHITECTURES, f"{artifact_path}.architecture", "must be x86_64 or aarch64")
        require(architecture not in seen_architectures, f"{artifact_path}.architecture", "is duplicated")
        seen_architectures.add(architecture)
        architecture_contract = ARCHITECTURES[architecture]
        expected_name = f"lean-{version}-{architecture_contract['suffix']}.tar.zst"
        name = require_string(artifact["name"], f"{artifact_path}.name")
        require(name == expected_name, f"{artifact_path}.name", f"must be {expected_name!r}")
        expected_url = release_base_url + name
        require(artifact["url"] == expected_url, f"{artifact_path}.url", f"must be immutable URL {expected_url!r}")
        require(artifact["checksumUrl"] == expected_url + ".sha256", f"{artifact_path}.checksumUrl", "must be the archive URL plus .sha256")
        require_sha256(artifact["sha256"], f"{artifact_path}.sha256")
        require_integer(artifact["size"], f"{artifact_path}.size", minimum=1)
        sass = require_array(artifact["sassArchitectures"], f"{artifact_path}.sassArchitectures")
        require(sass == architecture_contract["sass"], f"{artifact_path}.sassArchitectures", f"must be {architecture_contract['sass']!r}")

        manifest = require_object(artifact["manifest"], f"{artifact_path}.manifest")
        require_exact_keys(
            manifest,
            f"{artifact_path}.manifest",
            required={"schema", "name", "url", "sha256", "size", "fileCount"},
        )
        require(manifest["schema"] == MANIFEST_SCHEMA, f"{artifact_path}.manifest.schema", f"must be {MANIFEST_SCHEMA!r}")
        expected_manifest_name = f"lean-{version}-{architecture_contract['suffix']}.manifest.json"
        require(manifest["name"] == expected_manifest_name, f"{artifact_path}.manifest.name", f"must be {expected_manifest_name!r}")
        require(manifest["url"] == release_base_url + expected_manifest_name, f"{artifact_path}.manifest.url", "must be the immutable manifest release URL")
        require_sha256(manifest["sha256"], f"{artifact_path}.manifest.sha256")
        require_integer(manifest["size"], f"{artifact_path}.manifest.size", minimum=1)
        require_integer(manifest["fileCount"], f"{artifact_path}.manifest.fileCount", minimum=1)

    require(seen_architectures == set(ARCHITECTURES), f"{origin}.artifacts", "must cover x86_64 and aarch64")

    limitations = require_array(record["limitations"], f"{origin}.limitations")
    require(len(limitations) > 0, f"{origin}.limitations", "must not be empty")
    normalized_limitations = [require_string(item, f"{origin}.limitations[{index}]") for index, item in enumerate(limitations)]
    require(len(set(normalized_limitations)) == len(normalized_limitations), f"{origin}.limitations", "must not contain duplicates")
    return record


def validate_manifest(value: Any, origin: str = "manifest") -> dict[str, int]:
    manifest = require_object(value, origin)
    require(manifest.get("schema") == MANIFEST_SCHEMA, f"{origin}.schema", f"must be {MANIFEST_SCHEMA!r}")
    file_count = require_integer(manifest.get("fileCount"), f"{origin}.fileCount")
    files = require_array(manifest.get("files"), f"{origin}.files")
    require(file_count == len(files), f"{origin}.fileCount", f"declares {file_count}, but files contains {len(files)} entries")

    paths: set[str] = set()
    forbidden_sources: list[str] = []
    for index, raw_entry in enumerate(files):
        entry_path = f"{origin}.files[{index}]"
        entry = require_object(raw_entry, entry_path)
        require_exact_keys(entry, entry_path, required={"path", "sha256", "size", "type"})
        path = require_string(entry["path"], f"{entry_path}.path")
        require("\\" not in path, f"{entry_path}.path", "must use POSIX separators")
        pure_path = PurePosixPath(path)
        require(not pure_path.is_absolute(), f"{entry_path}.path", "must be relative")
        require(path not in {".", ".."} and ".." not in pure_path.parts, f"{entry_path}.path", "must not traverse outside the archive root")
        require(path not in paths, f"{entry_path}.path", "is duplicated")
        paths.add(path)
        require_sha256(entry["sha256"], f"{entry_path}.sha256")
        require_integer(entry["size"], f"{entry_path}.size")
        require(entry["type"] in {"file", "symlink"}, f"{entry_path}.type", "must be 'file' or 'symlink'")
        if path.startswith("src/lean/") and path.endswith(".lean"):
            forbidden_sources.append(path)

    if forbidden_sources:
        preview = ", ".join(forbidden_sources[:5])
        if len(forbidden_sources) > 5:
            preview += f", ... ({len(forbidden_sources)} total)"
        fail(origin, "contains forbidden installed Lean sources: " + preview)
    return {"fileCount": file_count, "privateLeanSources": 0}


def build_manifest(root: Path, output: Path) -> dict[str, Any]:
    """Build a deterministic manifest for the contents of an installed toolchain."""
    root = root.resolve()
    require(root.is_dir(), str(root), "installed toolchain root must be a directory")

    output = output.resolve()
    require(root not in output.parents, str(output), "manifest output must be outside the toolchain root")

    files: list[dict[str, Any]] = []

    def visit(directory: Path) -> None:
        try:
            children = sorted(directory.iterdir(), key=lambda path: path.name)
        except OSError as error:
            raise ContractError(f"{directory}: cannot list directory: {error}") from error

        for path in children:
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                try:
                    target = os.fsencode(os.readlink(path))
                except OSError as error:
                    raise ContractError(f"{path}: cannot read symlink: {error}") from error
                files.append(
                    {
                        "path": relative,
                        "sha256": hashlib.sha256(target).hexdigest(),
                        "size": len(target),
                        "type": "symlink",
                    }
                )
            elif path.is_dir():
                visit(path)
            elif path.is_file():
                try:
                    size = path.stat().st_size
                except OSError as error:
                    raise ContractError(f"{path}: cannot stat file: {error}") from error
                files.append(
                    {
                        "path": relative,
                        "sha256": file_sha256(path),
                        "size": size,
                        "type": "file",
                    }
                )
            else:
                fail(str(path), "unsupported installed-tree entry type")

    visit(root)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "fileCount": len(files),
        "files": files,
    }
    validate_manifest(manifest, str(output))
    write_json(output, manifest)
    return manifest


def load_release_records(records_dir: Path) -> list[dict[str, Any]]:
    if not records_dir.is_dir():
        raise ContractError(f"{records_dir}: release records directory does not exist")
    records: list[dict[str, Any]] = []
    ids: set[str] = set()
    versions: set[str] = set()
    for path in sorted(records_dir.glob("*.json")):
        record = validate_release(read_json(path), str(path))
        expected_name = f"{record['id']}.json"
        require(path.name == expected_name, str(path), f"filename must be {expected_name!r}")
        require(record["id"] not in ids, str(path), "duplicates an existing release id")
        require(record["version"] not in versions, str(path), "duplicates an existing toolchain version")
        ids.add(record["id"])
        versions.add(record["version"])
        records.append(record)
    records.sort(key=lambda record: (record["publishedAt"], record["id"]), reverse=True)
    return records


def release_summary(record: dict[str, Any]) -> dict[str, str]:
    return {
        "id": record["id"],
        "version": record["version"],
        "publishedAt": record["publishedAt"],
        "metadataUrl": f"./{record['id']}.json",
    }


def release_download_links(record: dict[str, Any]) -> list[str]:
    artifacts = {artifact["architecture"]: artifact for artifact in record["artifacts"]}
    links = []
    for architecture, label in (
        ("x86_64", "Linux x86_64"),
        ("aarch64", "Linux AArch64"),
    ):
        url = html.escape(artifacts[architecture]["url"], quote=True)
        links.append(f'<a href="{url}">{label}</a>')
    return links


def ensure_safe_output(output: Path, records_dir: Path, static_dir: Path) -> None:
    output = output.resolve()
    protected = {Path("/").resolve(), Path.home().resolve(), Path.cwd().resolve()}
    require(output not in protected, str(output), "refusing to replace a broad directory")
    for source in (records_dir.resolve(), static_dir.resolve()):
        require(output != source, str(output), "output must differ from input directories")
        require(output not in source.parents, str(output), "output must not contain an input directory")
        require(source not in output.parents, str(output), "output must not be inside an input directory")


def build_site(
    records_dir: Path,
    static_dir: Path,
    output_dir: Path,
    schema_dir: Path | None = None,
    status_path: Path | None = None,
) -> int:
    records = load_release_records(records_dir)
    build_status = None
    if status_path is not None:
        require(status_path.is_file(), str(status_path), "build status file does not exist")
        build_status = validate_build_status(read_json(status_path), str(status_path))
    if not static_dir.is_dir():
        raise ContractError(f"{static_dir}: static site directory does not exist")
    ensure_safe_output(output_dir, records_dir, static_dir)
    if schema_dir is not None:
        require(schema_dir.is_dir(), str(schema_dir), "schema directory does not exist")
        ensure_safe_output(output_dir, schema_dir, static_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(static_dir, output_dir)
    if schema_dir is not None:
        shutil.copytree(schema_dir, output_dir / "schema")

    summaries = [release_summary(record) for record in records]
    index = {"schema": INDEX_SCHEMA, "channel": "nightly", "releases": summaries}
    latest = {
        "schema": LATEST_SCHEMA,
        "channel": "nightly",
        "release": summaries[0] if summaries else None,
    }
    release_output = output_dir / "releases" / "v1"
    write_json(release_output / "index.json", index)
    write_json(release_output / "latest.json", latest)
    for record in records:
        write_json(release_output / f"{record['id']}.json", record)

    if build_status is not None:
        matching_release = next(
            (record for record in records if record["id"] == build_status["releaseId"]),
            None,
        )
        if build_status["state"] == "accepted":
            require(
                matching_release is not None,
                str(status_path),
                "accepted status requires an immutable release record",
            )
        elif build_status["state"] == "running" and matching_release is not None:
            build_status = dict(build_status)
            build_status["state"] = "accepted"
            build_status["updatedAt"] = matching_release["publishedAt"]
            build_status["message"] = (
                "Accepted and published after dual-architecture validation."
            )
        write_json(output_dir / "status" / "v1" / "nightly.json", build_status)

    index_path = output_dir / "index.html"
    try:
        template = index_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ContractError(f"{index_path}: cannot read site template: {error}") from error
    require(template.count("{{LATEST_STATUS}}") == 1, str(index_path), "must contain one {{LATEST_STATUS}} marker")
    require(template.count("{{RELEASE_ROWS}}") == 1, str(index_path), "must contain one {{RELEASE_ROWS}} marker")
    require(template.count("{{LATEST_INSTALL}}") == 1, str(index_path), "must contain one {{LATEST_INSTALL}} marker")
    require(template.count("{{LATEST_COMPATIBILITY}}") == 1, str(index_path), "must contain one {{LATEST_COMPATIBILITY}} marker")
    status_line = None
    latest_install = ""
    latest_compatibility = ""
    if build_status is not None and build_status["state"] != "accepted":
        state = html.escape(build_status["state"])
        status_line = (
            f'<span class="status-state status-{state}">{state}</span> '
            f"<strong>{html.escape(build_status['releaseId'])}</strong> — "
            f"{html.escape(build_status['message'])} "
            '<a href="status/v1/nightly.json">Machine-readable status</a>'
        )
    if records:
        newest = records[0]
        version_match = VERSION_RE.fullmatch(newest["version"])
        assert version_match is not None
        toolchain = html.escape(newest["installation"]["elanToolchain"])
        latest_install = (
            '<pre class="install-command"><code>'
            f"elan toolchain install {toolchain}"
            "</code></pre>"
        )
        latest_compatibility = (
            f"<strong>Compatibility:</strong> Linux x86_64 or AArch64 · "
            f"Lean {html.escape(version_match.group('base'))} · CUDA 13"
        )
        newest_downloads = " · ".join(release_download_links(newest))
        accepted_line = (
            '<span class="status-state status-accepted">accepted</span> '
            f"<strong>{html.escape(newest['id'])}</strong> — "
            f"{html.escape(newest['version'])}. "
            f"Downloads: {newest_downloads}. "
            f"<a href=\"releases/v1/{html.escape(newest['id'])}.json\">Immutable metadata</a>"
        )
        latest_status = f"{status_line}<br>{accepted_line}" if status_line else accepted_line
        rows = []
        for record in records[:MAX_RELEASE_ROWS]:
            downloads = "".join(release_download_links(record))
            rows.append(
                "<article class=\"release-row\">"
                "<div>"
                f"<h3>{html.escape(record['id'])}</h3>"
                f"<p><code>{html.escape(record['version'])}</code></p>"
                "</div>"
                "<div class=\"release-links\">"
                f"{downloads}"
                f"<a href=\"releases/v1/{html.escape(record['id'])}.json\">metadata</a>"
                "</div>"
                "</article>"
            )
        release_rows = "\n".join(rows)
    else:
        latest_status = status_line or (
            "<strong>No public nightly yet.</strong> The channel contract and publishing path are ready."
        )
        release_rows = '<article class="release-row"><p>No release records have been published.</p></article>'
    rendered = (
        template.replace("{{LATEST_STATUS}}", latest_status)
        .replace("{{LATEST_INSTALL}}", latest_install)
        .replace("{{LATEST_COMPATIBILITY}}", latest_compatibility)
        .replace("{{RELEASE_ROWS}}", release_rows)
    )
    index_path.write_text(rendered, encoding="utf-8")
    return len(records)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_sha256_sidecar(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ContractError(f"{path}: cannot read checksum sidecar: {error}") from error
    if not text:
        fail(str(path), "checksum sidecar is empty")
    digest = text.split()[0]
    require_sha256(digest, str(path))
    return digest


def artifact_from_files(
    *,
    architecture: str,
    version: str,
    release_id: str,
    archive: Path,
    manifest: Path,
) -> dict[str, Any]:
    require(architecture in ARCHITECTURES, str(archive), f"unknown architecture {architecture}")
    require(archive.is_file(), str(archive), "archive must be a file")
    require(manifest.is_file(), str(manifest), "manifest must be a file")
    sidecar = Path(str(archive) + ".sha256")
    digest = file_sha256(archive)
    if sidecar.is_file():
        sidecar_digest = read_sha256_sidecar(sidecar)
        require(
            sidecar_digest == digest,
            str(sidecar),
            "does not match the archive contents",
        )
    manifest_summary = validate_manifest(read_json(manifest), str(manifest))
    suffix = ARCHITECTURES[architecture]["suffix"]
    name = f"lean-{version}-{suffix}.tar.zst"
    require(archive.name == name, str(archive), f"must be named {name}")
    manifest_name = f"lean-{version}-{suffix}.manifest.json"
    require(manifest.name == manifest_name, str(manifest), f"must be named {manifest_name}")
    release_base_url = f"https://github.com/{DISTRIBUTION_REPOSITORY}/releases/download/{release_id}/"
    return {
        "hostSystem": "Linux",
        "architecture": architecture,
        "name": name,
        "url": release_base_url + name,
        "checksumUrl": release_base_url + name + ".sha256",
        "sha256": digest,
        "size": archive.stat().st_size,
        "sassArchitectures": list(ARCHITECTURES[architecture]["sass"]),
        "manifest": {
            "schema": MANIFEST_SCHEMA,
            "name": manifest_name,
            "url": release_base_url + manifest_name,
            "sha256": file_sha256(manifest),
            "size": manifest.stat().st_size,
            "fileCount": manifest_summary["fileCount"],
        },
    }


def build_record(
    *,
    release_id: str,
    version: str,
    commit: str,
    published_at: str,
    workflow_url: str,
    cuda_toolkit_version: str,
    ptx_architecture: str,
    registered: int,
    failures: int,
    skipped: int,
    umbrella_modules: int,
    linux_archive: Path,
    linux_manifest: Path,
    linux_aarch64_archive: Path,
    linux_aarch64_manifest: Path,
    tree: str | None = None,
    extracted_smoke: bool = True,
) -> dict[str, Any]:
    source: dict[str, Any] = {
        "visibility": "private",
        "commit": commit,
    }
    if tree is not None:
        source["tree"] = tree
    record = {
        "schema": RELEASE_SCHEMA,
        "channel": "nightly",
        "id": release_id,
        "version": version,
        "publishedAt": published_at,
        "source": source,
        "build": {
            "cudaToolkitVersion": cuda_toolkit_version,
            "ptxArchitecture": ptx_architecture,
            "workflowUrl": workflow_url,
            "validation": {
                "registered": registered,
                "failures": failures,
                "skipped": skipped,
                "umbrellaModules": umbrella_modules,
                "extractedSmoke": extracted_smoke,
            },
        },
        "gates": {
            "dualArchitectureCI": "passed",
            "h100": "not-run",
            "performanceClaims": False,
        },
        "contentPolicy": {
            "privateLeanSources": "excluded",
            "sdkHeaders": "included",
        },
        "installation": {
            "repository": DISTRIBUTION_REPOSITORY,
            "elanToolchain": f"{DISTRIBUTION_REPOSITORY}:{release_id}",
        },
        "artifacts": [
            artifact_from_files(
                architecture="x86_64",
                version=version,
                release_id=release_id,
                archive=linux_archive,
                manifest=linux_manifest,
            ),
            artifact_from_files(
                architecture="aarch64",
                version=version,
                release_id=release_id,
                archive=linux_aarch64_archive,
                manifest=linux_aarch64_manifest,
            ),
        ],
        "limitations": list(DEFAULT_LIMITATIONS),
    }
    return validate_release(record)


def command_validate(arguments: argparse.Namespace) -> int:
    count = 0
    if arguments.records_dir is not None:
        count += len(load_release_records(arguments.records_dir))
    for path in arguments.records:
        validate_release(read_json(path), str(path))
        count += 1
    print(f"validated {count} release record(s)")
    return 0


def command_verify_manifest(arguments: argparse.Namespace) -> int:
    for path in arguments.manifests:
        summary = validate_manifest(read_json(path), str(path))
        print(
            json.dumps(
                {
                    "file": str(path),
                    "fileCount": summary["fileCount"],
                    "privateLeanSources": 0,
                    "sha256": file_sha256(path),
                },
                sort_keys=True,
            )
        )
    return 0


def command_build_manifest(arguments: argparse.Namespace) -> int:
    manifest = build_manifest(arguments.root, arguments.output)
    print(
        json.dumps(
            {
                "file": str(arguments.output),
                "fileCount": manifest["fileCount"],
                "privateLeanSources": 0,
                "sha256": file_sha256(arguments.output),
            },
            sort_keys=True,
        )
    )
    return 0


def command_build_status(arguments: argparse.Namespace) -> int:
    status = build_status(
        state=arguments.state,
        release_id=arguments.release_id,
        started_at=arguments.started_at,
        updated_at=arguments.updated_at,
        message=arguments.message,
    )
    write_json(arguments.output, status)
    print(
        json.dumps(
            {"file": str(arguments.output), "releaseId": status["releaseId"], "state": status["state"]},
            sort_keys=True,
        )
    )
    return 0


def command_build_site(arguments: argparse.Namespace) -> int:
    count = build_site(
        arguments.records_dir,
        arguments.static_dir,
        arguments.output_dir,
        arguments.schema_dir,
        arguments.status,
    )
    print(f"built {arguments.output_dir} from {count} release record(s)")
    return 0


def command_build_record(arguments: argparse.Namespace) -> int:
    record = build_record(
        release_id=arguments.release_id,
        version=arguments.version,
        commit=arguments.commit,
        tree=arguments.tree,
        published_at=arguments.published_at,
        workflow_url=arguments.workflow_url,
        cuda_toolkit_version=arguments.cuda_toolkit_version,
        ptx_architecture=arguments.ptx_architecture,
        registered=arguments.registered,
        failures=arguments.failures,
        skipped=arguments.skipped,
        umbrella_modules=arguments.umbrella_modules,
        extracted_smoke=arguments.extracted_smoke,
        linux_archive=arguments.linux_archive,
        linux_manifest=arguments.linux_manifest,
        linux_aarch64_archive=arguments.linux_aarch64_archive,
        linux_aarch64_manifest=arguments.linux_aarch64_manifest,
    )
    write_json(arguments.output, record)
    print(
        json.dumps(
            {
                "file": str(arguments.output),
                "id": record["id"],
                "version": record["version"],
            },
            sort_keys=True,
        )
    )
    return 0


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate immutable release records")
    validate_parser.add_argument("records", nargs="*", type=Path)
    validate_parser.add_argument("--records-dir", type=Path)
    validate_parser.set_defaults(handler=command_validate)

    manifest_parser = subparsers.add_parser(
        "verify-manifest",
        help="verify deterministic manifests and reject installed private Lean sources",
    )
    manifest_parser.add_argument("manifests", nargs="+", type=Path)
    manifest_parser.set_defaults(handler=command_verify_manifest)

    build_manifest_parser = subparsers.add_parser(
        "build-manifest",
        help="create a deterministic manifest for an installed toolchain",
    )
    build_manifest_parser.add_argument("root", type=Path)
    build_manifest_parser.add_argument("--output", type=Path, required=True)
    build_manifest_parser.set_defaults(handler=command_build_manifest)

    site_parser = subparsers.add_parser("build-site", help="validate records and build the static site")
    status_parser = subparsers.add_parser(
        "build-status",
        help="write a validated nightly build status record",
    )
    status_parser.add_argument("--state", choices=("running", "accepted", "failed"), required=True)
    status_parser.add_argument("--release-id", required=True)
    status_parser.add_argument("--started-at", required=True)
    status_parser.add_argument("--updated-at", required=True)
    status_parser.add_argument("--message", required=True)
    status_parser.add_argument("--output", type=Path, required=True)
    status_parser.set_defaults(handler=command_build_status)

    site_parser.add_argument("--records-dir", type=Path, required=True)
    site_parser.add_argument("--static-dir", type=Path, required=True)
    site_parser.add_argument("--schema-dir", type=Path)
    site_parser.add_argument("--status", type=Path)
    site_parser.add_argument("--output-dir", type=Path, required=True)
    site_parser.set_defaults(handler=command_build_site)

    record_parser = subparsers.add_parser(
        "build-record",
        help="write a validated nightly release record from published artifacts",
    )
    record_parser.add_argument("--release-id", required=True)
    record_parser.add_argument("--version", required=True)
    record_parser.add_argument("--commit", required=True)
    record_parser.add_argument("--tree")
    record_parser.add_argument("--published-at", required=True)
    record_parser.add_argument("--workflow-url", required=True)
    record_parser.add_argument("--cuda-toolkit-version", required=True)
    record_parser.add_argument("--ptx-architecture", required=True)
    record_parser.add_argument("--registered", type=int, required=True)
    record_parser.add_argument("--failures", type=int, default=0)
    record_parser.add_argument("--skipped", type=int, required=True)
    record_parser.add_argument("--umbrella-modules", type=int, required=True)
    record_parser.add_argument("--extracted-smoke", action=argparse.BooleanOptionalAction, default=True)
    record_parser.add_argument("--linux-archive", type=Path, required=True)
    record_parser.add_argument("--linux-manifest", type=Path, required=True)
    record_parser.add_argument("--linux-aarch64-archive", type=Path, required=True)
    record_parser.add_argument("--linux-aarch64-manifest", type=Path, required=True)
    record_parser.add_argument("--output", type=Path, required=True)
    record_parser.set_defaults(handler=command_build_record)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        return arguments.handler(arguments)
    except ContractError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

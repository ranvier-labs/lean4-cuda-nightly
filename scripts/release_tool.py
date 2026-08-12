#!/usr/bin/env python3
"""Validate Lean CUDA release metadata and build the static distribution site."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from typing import Any, NoReturn


RELEASE_SCHEMA = "lean.cuda.release/v1"
MANIFEST_SCHEMA = "lean.cuda.release-manifest/v1"
INDEX_SCHEMA = "lean.cuda.release-index/v1"
LATEST_SCHEMA = "lean.cuda.latest/v1"
DISTRIBUTION_REPOSITORY = "ranvier-labs/lean4-cuda-nightly"

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
) -> int:
    records = load_release_records(records_dir)
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

    index_path = output_dir / "index.html"
    try:
        template = index_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ContractError(f"{index_path}: cannot read site template: {error}") from error
    require(template.count("{{LATEST_STATUS}}") == 1, str(index_path), "must contain one {{LATEST_STATUS}} marker")
    require(template.count("{{RELEASE_ROWS}}") == 1, str(index_path), "must contain one {{RELEASE_ROWS}} marker")
    if records:
        newest = records[0]
        latest_status = (
            f"<strong>{html.escape(newest['id'])}</strong> — "
            f"{html.escape(newest['version'])}. "
            f"<a href=\"releases/v1/{html.escape(newest['id'])}.json\">Immutable metadata</a>"
        )
        rows = []
        for record in records:
            rows.append(
                "<article class=\"release-row\">"
                "<div>"
                f"<h3>{html.escape(record['id'])}</h3>"
                f"<p><code>{html.escape(record['version'])}</code></p>"
                "</div>"
                f"<a href=\"releases/v1/{html.escape(record['id'])}.json\">metadata</a>"
                "</article>"
            )
        release_rows = "\n".join(rows)
    else:
        latest_status = "<strong>No public nightly yet.</strong> The channel contract and publishing path are ready."
        release_rows = '<article class="release-row"><p>No release records have been published.</p></article>'
    rendered = template.replace("{{LATEST_STATUS}}", latest_status).replace("{{RELEASE_ROWS}}", release_rows)
    index_path.write_text(rendered, encoding="utf-8")
    return len(records)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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


def command_build_site(arguments: argparse.Namespace) -> int:
    count = build_site(
        arguments.records_dir,
        arguments.static_dir,
        arguments.output_dir,
        arguments.schema_dir,
    )
    print(f"built {arguments.output_dir} from {count} release record(s)")
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

    site_parser = subparsers.add_parser("build-site", help="validate records and build the static site")
    site_parser.add_argument("--records-dir", type=Path, required=True)
    site_parser.add_argument("--static-dir", type=Path, required=True)
    site_parser.add_argument("--schema-dir", type=Path)
    site_parser.add_argument("--output-dir", type=Path, required=True)
    site_parser.set_defaults(handler=command_build_site)
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

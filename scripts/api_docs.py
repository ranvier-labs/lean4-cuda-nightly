#!/usr/bin/env python3
"""Build and publish source-safe API documentation for an accepted nightly."""

from __future__ import annotations

import argparse
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, NoReturn
from urllib.parse import unquote, urlsplit


DOCGEN_REPOSITORY = "cpehle/doc-gen4"
DOCUMENTED_PREFIXES = (
    "Lean.Compiler",
    "Lean.Cuda",
    "Cuda",
    "Lake.Build.Cuda",
    "Lean.Compiler.LCNF.CudaExternBody",
    "Lean.Compiler.LCNF.CudaGround",
    "Lean.Compiler.LCNF.CudaRuntime",
    "Lean.Compiler.LCNF.CudaRuntimeAudit",
    "Lean.Compiler.LCNF.CudaValidate",
    "Lean.Compiler.LCNF.EmitCUDA",
    "Lean.Compiler.LowPrecision",
)
REQUIRED_PAGES = tuple(prefix.replace(".", "/") + ".html" for prefix in DOCUMENTED_PREFIXES)
FORBIDDEN_SUFFIXES = (".lean", ".tar", ".zst", ".log")
FORBIDDEN_CONTENT = (
    b"/home/",
    b"/tmp/",
    b"lean4-cuda-backend",
    b"git@github.com",
    b"github.com/leanprover/lean4/blob/",
    b"github.com/leanprover/lean4/tree/",
    b"vscode://",
    b"file://",
    b">source</a>",
    b'class="equation ',
)


class ApiDocsError(Exception):
    """API documentation input or output violates the publication contract."""


class LinkParser(HTMLParser):
    """Collect links from generated HTML without evaluating it."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        for name, value in attrs:
            if name == "href" and value is not None:
                self.links.append(value)


def fail(message: str) -> NoReturn:
    raise ApiDocsError(message)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ApiDocsError(f"{path}: cannot read file: {error}") from error
    except json.JSONDecodeError as error:
        raise ApiDocsError(f"{path}: invalid JSON: {error}") from error


def module_digests(path: Path) -> dict[str, str]:
    manifest = read_json(path)
    if not isinstance(manifest, dict) or manifest.get("schema") != "lean.cuda.release-manifest/v1":
        fail(f"{path}: invalid release manifest schema")
    files = manifest.get("files")
    if not isinstance(files, list):
        fail(f"{path}: files must be an array")
    modules: dict[str, str] = {}
    for entry in files:
        if not isinstance(entry, dict):
            fail(f"{path}: file entries must be objects")
        name = entry.get("path")
        digest = entry.get("sha256")
        if (
            entry.get("type") == "file"
            and isinstance(name, str)
            and name.endswith((".olean", ".ilean"))
        ):
            if not isinstance(digest, str) or len(digest) != 64:
                fail(f"{path}: invalid module digest for {name}")
            modules[name] = digest
    if not modules:
        fail(f"{path}: contains no compiled Lean modules")
    return modules


def compare_module_manifests(x86_manifest: Path, aarch64_manifest: Path) -> int:
    x86_modules = module_digests(x86_manifest)
    aarch64_modules = module_digests(aarch64_manifest)
    mismatches = sorted(
        name
        for name in x86_modules.keys() | aarch64_modules.keys()
        if x86_modules.get(name) != aarch64_modules.get(name)
    )
    if mismatches:
        preview = ", ".join(mismatches[:8])
        fail(
            f"compiled Lean modules differ across architectures ({len(mismatches)}): {preview}"
        )
    return len(x86_modules)


def iter_source_links(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "sourceLink":
                yield item
            yield from iter_source_links(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_source_links(item)


def audit_docs(root: Path) -> dict[str, int]:
    if not root.is_dir():
        fail(f"{root}: generated documentation directory does not exist")
    for relative in REQUIRED_PAGES:
        if not (root / relative).is_file():
            fail(f"{root}: missing required page {relative}")

    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        fail(f"{root}: generated documentation is empty")
    total_bytes = 0
    local_links: list[tuple[Path, str]] = []
    for path in files:
        if path.name.lower().endswith(FORBIDDEN_SUFFIXES):
            fail(f"{path}: forbidden generated file type")
        data = path.read_bytes()
        total_bytes += len(data)
        lowered = data.lower()
        for needle in FORBIDDEN_CONTENT:
            if needle in lowered:
                fail(f"{path}: contains forbidden publication content {needle.decode()!r}")
        if path.suffix == ".html":
            parser = LinkParser()
            try:
                parser.feed(data.decode("utf-8"))
            except UnicodeDecodeError as error:
                raise ApiDocsError(f"{path}: HTML is not UTF-8: {error}") from error
            local_links.extend((path, link) for link in parser.links)
        if path.suffix == ".bmp":
            try:
                value = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ApiDocsError(f"{path}: declaration data is not JSON: {error}") from error
            if any(link not in (None, "") for link in iter_source_links(value)):
                fail(f"{path}: contains a non-empty source link")
    resolved_root = root.resolve()
    for page, link in local_links:
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        decoded = unquote(parsed.path)
        target = (
            resolved_root / decoded.lstrip("/")
            if decoded.startswith("/")
            else page.parent / decoded
        ).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError:
            fail(f"{page}: local link escapes documentation root: {link}")
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            fail(f"{page}: broken local link: {link}")
    return {"files": len(files), "bytes": total_bytes}


def run_checked(arguments: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=None,
    )
    if completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout, file=sys.stderr, end="")
        fail(f"command failed with exit code {completed.returncode}: {' '.join(arguments)}")
    return completed.stdout


def artifacts_by_architecture(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = record.get("artifacts")
    if not isinstance(artifacts, list):
        fail("release record artifacts must be an array")
    by_architecture = {
        artifact.get("architecture"): artifact
        for artifact in artifacts
        if isinstance(artifact, dict)
    }
    if set(by_architecture) != {"x86_64", "aarch64"}:
        fail("release record must contain exactly x86_64 and aarch64 artifacts")
    return by_architecture


def build_docs(
    *,
    record_path: Path,
    x86_manifest: Path,
    aarch64_manifest: Path,
    toolchain: Path,
    docgen: Path,
    build_dir: Path,
    docgen_commit: str,
) -> dict[str, Any]:
    toolchain = toolchain.resolve()
    docgen = docgen.resolve()
    build_dir = build_dir.resolve()
    record = read_json(record_path)
    if not isinstance(record, dict):
        fail(f"{record_path}: release record must be an object")
    artifacts_by_architecture(record)
    module_count = compare_module_manifests(x86_manifest, aarch64_manifest)

    lake = toolchain / "bin" / "lake"
    lean = toolchain / "bin" / "lean"
    if not lake.is_file() or not lean.is_file():
        fail(f"{toolchain}: does not contain bin/lean and bin/lake")
    if not (docgen / "static").is_dir():
        fail(f"{docgen}: doc-gen4 static directory does not exist")
    if build_dir.exists() and any(build_dir.iterdir()):
        fail(f"{build_dir}: build directory must be empty")
    build_dir.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    environment.update(
        {
            "LEAN_SYSROOT": str(toolchain.resolve()),
            "DOCGEN_SRC": "none",
            "DISABLE_EQUATIONS": "1",
        }
    )
    actual_commit = run_checked(
        ["git", "rev-parse", "HEAD"], cwd=docgen, env=environment
    ).strip()
    if actual_commit != docgen_commit:
        fail(f"doc-gen4 checkout is {actual_commit}, expected {docgen_commit}")
    lean_version = run_checked([str(lean), "--version"], cwd=docgen, env=environment)
    version = record.get("version")
    if not isinstance(version, str) or version not in lean_version:
        fail(f"toolchain version does not match release record {version!r}")

    run_checked([str(lake), "build"], cwd=docgen, env=environment)
    executable = docgen / ".lake" / "build" / "bin" / "doc-gen4"
    if not executable.is_file():
        fail(f"{executable}: doc-gen4 build did not produce an executable")
    for prefix in DOCUMENTED_PREFIXES:
        run_checked(
            [str(executable), "genCore", prefix, "--build", str(build_dir)],
            cwd=docgen,
            env=environment,
        )
    run_checked(
        [
            str(executable),
            "index",
            "--build",
            str(build_dir),
            "--static",
            str(docgen / "static"),
        ],
        cwd=docgen,
        env=environment,
    )

    docs_root = build_dir / "doc"
    audit = audit_docs(docs_root)
    metadata = {
        "schema": "lean.cuda.api-docs/v1",
        "releaseId": record.get("id"),
        "version": version,
        "architectures": ["x86_64", "aarch64"],
        "compiledModuleCount": module_count,
        "documentedPrefixes": list(DOCUMENTED_PREFIXES),
        "generator": {
            "repository": DOCGEN_REPOSITORY,
            "commit": docgen_commit,
        },
        "output": audit,
    }
    (docs_root / "api-docs.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    audit_docs(docs_root)
    return metadata


def redirect_page(target: str) -> str:
    escaped = html.escape(target, quote=True)
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0;url={escaped}">'
        f'<link rel="canonical" href="{escaped}">'
        "<title>Lean CUDA API reference</title></head>"
        f'<body><p><a href="{escaped}">Open the API reference</a></p></body></html>\n'
    )


def api_landing(metadata: dict[str, Any]) -> str:
    release_id = html.escape(str(metadata["releaseId"]))
    version = html.escape(str(metadata["version"]))
    module_count = int(metadata["compiledModuleCount"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Lean CUDA compiler and backend API reference.">
  <title>API reference · Lean CUDA</title>
  <link rel="stylesheet" href="../styles.css">
</head>
<body>
  <main>
    <nav><a class="brand" href="../index.html">lean cuda</a></nav>
    <header class="page-hero">
      <h1>API reference</h1>
      <p class="lede">Compiler, CUDA backend, host runtime, and Lake integration declarations for {release_id}.</p>
    </header>
    <section>
      <h2>{version}</h2>
      <p>The accepted x86_64 and AArch64 distributions contain the same {module_count:,} compiled Lean modules.</p>
      <p class="actions">
        <a href="{release_id}/x86_64/">Linux x86_64</a>
        <a href="{release_id}/aarch64/">Linux AArch64</a>
      </p>
    </section>
    <footer><p><a href="../index.html">Lean CUDA</a> · <a href="../docs/index.html">Guide</a></p></footer>
  </main>
</body>
</html>
"""


def publish_docs(build_dir: Path, site_dir: Path) -> dict[str, Any]:
    docs_root = build_dir / "doc"
    audit_docs(docs_root)
    metadata = read_json(docs_root / "api-docs.json")
    if not isinstance(metadata, dict) or metadata.get("schema") != "lean.cuda.api-docs/v1":
        fail(f"{docs_root / 'api-docs.json'}: invalid API documentation metadata")
    release_id = metadata.get("releaseId")
    if not isinstance(release_id, str) or not release_id.startswith("nightly-"):
        fail("API documentation metadata has an invalid release ID")
    api_root = site_dir / "api"
    api_root.mkdir(parents=True, exist_ok=True)
    for architecture in ("x86_64", "aarch64"):
        destination = api_root / release_id / architecture
        if destination.exists():
            fail(f"{destination}: refusing to replace existing documentation")
        shutil.copytree(docs_root, destination)
        alias = api_root / architecture
        alias.mkdir(parents=True, exist_ok=True)
        (alias / "index.html").write_text(
            redirect_page(f"../{release_id}/{architecture}/"), encoding="utf-8"
        )
    (api_root / "index.html").write_text(api_landing(metadata), encoding="utf-8")
    return metadata


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare = subparsers.add_parser("compare-manifests")
    compare.add_argument("--x86-manifest", type=Path, required=True)
    compare.add_argument("--aarch64-manifest", type=Path, required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--record", type=Path, required=True)
    build.add_argument("--x86-manifest", type=Path, required=True)
    build.add_argument("--aarch64-manifest", type=Path, required=True)
    build.add_argument("--toolchain", type=Path, required=True)
    build.add_argument("--docgen", type=Path, required=True)
    build.add_argument("--build-dir", type=Path, required=True)
    build.add_argument("--docgen-commit", required=True)

    publish = subparsers.add_parser("publish")
    publish.add_argument("--build-dir", type=Path, required=True)
    publish.add_argument("--site-dir", type=Path, required=True)
    return parser


def main() -> int:
    arguments = make_parser().parse_args()
    try:
        if arguments.command == "compare-manifests":
            count = compare_module_manifests(
                arguments.x86_manifest, arguments.aarch64_manifest
            )
            print(f"verified {count} identical compiled Lean modules")
        elif arguments.command == "build":
            metadata = build_docs(
                record_path=arguments.record,
                x86_manifest=arguments.x86_manifest,
                aarch64_manifest=arguments.aarch64_manifest,
                toolchain=arguments.toolchain,
                docgen=arguments.docgen,
                build_dir=arguments.build_dir,
                docgen_commit=arguments.docgen_commit,
            )
            print(json.dumps(metadata, sort_keys=True))
        elif arguments.command == "publish":
            metadata = publish_docs(arguments.build_dir, arguments.site_dir)
            print(f"published API documentation for {metadata['releaseId']}")
    except ApiDocsError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

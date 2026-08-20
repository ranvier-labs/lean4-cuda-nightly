from __future__ import annotations

from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.release_tool import (
    CUDA_UPSTREAM_REPOSITORY,
    ContractError,
    build_manifest,
    build_record,
    build_site,
    load_release_records,
    validate_manifest,
    validate_release,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "nightly-2026-08-12.json"


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name == "href" and value is not None:
                self.links.append(value)


class ReleaseValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.record = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_valid_release(self) -> None:
        self.assertEqual(validate_release(self.record)["id"], "nightly-2026-08-12")

    def test_version_commit_must_match(self) -> None:
        self.record["source"]["commit"] = "f" * 40
        with self.assertRaisesRegex(ContractError, "short commit suffix"):
            validate_release(self.record)

    def test_both_architectures_are_required(self) -> None:
        self.record["artifacts"][1]["architecture"] = "x86_64"
        with self.assertRaisesRegex(ContractError, "duplicated"):
            validate_release(self.record)

    def test_performance_claim_requires_h100(self) -> None:
        self.record["gates"]["performanceClaims"] = True
        with self.assertRaisesRegex(ContractError, "must be false"):
            validate_release(self.record)

    def test_unknown_fields_fail_closed(self) -> None:
        self.record["sourceUrl"] = "https://example.invalid/private"
        with self.assertRaisesRegex(ContractError, "unknown fields"):
            validate_release(self.record)

    def test_distribution_repository_is_pinned(self) -> None:
        self.record["installation"]["repository"] = "attacker/toolchains"
        self.record["installation"]["elanToolchain"] = (
            "attacker/toolchains:nightly-2026-08-12"
        )
        with self.assertRaisesRegex(ContractError, "ranvier-labs/lean4-cuda-nightly"):
            validate_release(self.record)

    def test_cuda_upstream_is_the_private_ranvier_repository(self) -> None:
        self.assertEqual(CUDA_UPSTREAM_REPOSITORY, "ranvier-labs/lean4-cuda-backend")


class ManifestPolicyTests(unittest.TestCase):
    def entry(self, path: str) -> dict[str, object]:
        return {
            "path": path,
            "sha256": "0" * 64,
            "size": 1,
            "type": "file",
        }

    def test_compiled_tree_and_sdk_headers_pass(self) -> None:
        manifest = {
            "schema": "lean.cuda.release-manifest/v1",
            "fileCount": 3,
            "files": [
                self.entry("bin/lean"),
                self.entry("lib/lean/Lean/Cuda.olean"),
                self.entry("include/lean/lean_cuda_device_runtime.cuh"),
            ],
        }
        self.assertEqual(validate_manifest(manifest)["privateLeanSources"], 0)

    def test_private_lean_source_is_rejected(self) -> None:
        manifest = {
            "schema": "lean.cuda.release-manifest/v1",
            "fileCount": 1,
            "files": [self.entry("src/lean/Lean/Compiler/LCNF/EmitC.lean")],
        }
        with self.assertRaisesRegex(ContractError, "forbidden installed Lean sources"):
            validate_manifest(manifest)

    def test_traversal_is_rejected(self) -> None:
        manifest = {
            "schema": "lean.cuda.release-manifest/v1",
            "fileCount": 1,
            "files": [self.entry("../private.lean")],
        }
        with self.assertRaisesRegex(ContractError, "must not traverse"):
            validate_manifest(manifest)

    def test_build_manifest_is_deterministic_and_symlink_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            toolchain = temporary_root / "lean-toolchain"
            (toolchain / "bin").mkdir(parents=True)
            (toolchain / "lib" / "lean").mkdir(parents=True)
            (toolchain / "bin" / "lean").write_bytes(b"lean executable\n")
            (toolchain / "lib" / "lean" / "Cuda.olean").write_bytes(b"compiled module\n")
            (toolchain / "bin" / "lean-link").symlink_to("lean")
            output = temporary_root / "toolchain.manifest.json"

            first = build_manifest(toolchain, output)
            first_bytes = output.read_bytes()
            second = build_manifest(toolchain, output)

            self.assertEqual(first, second)
            self.assertEqual(output.read_bytes(), first_bytes)
            self.assertEqual(
                [entry["path"] for entry in first["files"]],
                ["bin/lean", "bin/lean-link", "lib/lean/Cuda.olean"],
            )
            symlink = first["files"][1]
            self.assertEqual(symlink["type"], "symlink")
            self.assertEqual(symlink["size"], len(b"lean"))
            self.assertEqual(validate_manifest(first)["privateLeanSources"], 0)

    def test_build_manifest_rejects_private_sources_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            toolchain = temporary_root / "lean-toolchain"
            private_source = toolchain / "src" / "lean" / "Lean" / "Secret.lean"
            private_source.parent.mkdir(parents=True)
            private_source.write_text("private\n", encoding="utf-8")
            output = temporary_root / "toolchain.manifest.json"

            with self.assertRaisesRegex(ContractError, "forbidden installed Lean sources"):
                build_manifest(toolchain, output)
            self.assertFalse(output.exists())

    def test_build_manifest_output_must_be_outside_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            toolchain = Path(temporary) / "lean-toolchain"
            toolchain.mkdir()
            with self.assertRaisesRegex(ContractError, "outside the toolchain root"):
                build_manifest(toolchain, toolchain / "manifest.json")


class BuildRecordTests(unittest.TestCase):
    def write_artifact(
        self,
        directory: Path,
        *,
        version: str,
        suffix: str,
        payload: bytes,
        files: list[str],
    ) -> tuple[Path, Path]:
        archive = directory / f"lean-{version}-{suffix}.tar.zst"
        archive.write_bytes(payload)
        sidecar = Path(str(archive) + ".sha256")
        digest = hashlib.sha256(payload).hexdigest()
        sidecar.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
        manifest = directory / f"lean-{version}-{suffix}.manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema": "lean.cuda.release-manifest/v1",
                    "fileCount": len(files),
                    "files": [
                        {
                            "path": path,
                            "sha256": "0" * 64,
                            "size": 1,
                            "type": "file",
                        }
                        for path in files
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return archive, manifest

    def test_build_record_from_dual_architecture_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            version = "4.33.0-cuda-nightly.20260820.g0123456"
            linux_archive, linux_manifest = self.write_artifact(
                directory,
                version=version,
                suffix="linux",
                payload=b"linux-toolchain",
                files=["bin/lean", "include/lean/lean_cuda.h", "lib/lean/Cuda.olean"],
            )
            arm_archive, arm_manifest = self.write_artifact(
                directory,
                version=version,
                suffix="linux_aarch64",
                payload=b"aarch64-toolchain",
                files=["bin/lean", "include/lean/lean_cuda.h", "lib/lean/Cuda.olean"],
            )
            record = build_record(
                release_id="nightly-2026-08-20",
                version=version,
                commit="0123456789abcdef0123456789abcdef01234567",
                tree="89abcdef0123456789abcdef0123456789abcdef",
                published_at="2026-08-20T08:30:00Z",
                workflow_url="https://github.com/ranvier-labs/lean4-cuda-backend/actions/runs/1",
                cuda_toolkit_version="13.0.88",
                ptx_architecture="compute_90",
                registered=4035,
                failures=0,
                skipped=83,
                umbrella_modules=66,
                linux_archive=linux_archive,
                linux_manifest=linux_manifest,
                linux_aarch64_archive=arm_archive,
                linux_aarch64_manifest=arm_manifest,
            )
            self.assertEqual(record["id"], "nightly-2026-08-20")
            self.assertEqual(record["gates"]["dualArchitectureCI"], "passed")
            self.assertFalse(record["gates"]["performanceClaims"])
            self.assertEqual(
                [artifact["architecture"] for artifact in record["artifacts"]],
                ["x86_64", "aarch64"],
            )
            write_output = directory / "written.json"
            write_json(write_output, record)
            self.assertEqual(validate_release(json.loads(write_output.read_text()))["id"], record["id"])

    def test_build_record_rejects_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            version = "4.33.0-cuda-nightly.20260820.g0123456"
            linux_archive, linux_manifest = self.write_artifact(
                directory,
                version=version,
                suffix="linux",
                payload=b"linux-toolchain",
                files=["bin/lean"],
            )
            Path(str(linux_archive) + ".sha256").write_text("0" * 64 + "  broken\n", encoding="utf-8")
            arm_archive, arm_manifest = self.write_artifact(
                directory,
                version=version,
                suffix="linux_aarch64",
                payload=b"aarch64-toolchain",
                files=["bin/lean"],
            )
            with self.assertRaisesRegex(ContractError, "does not match the archive contents"):
                build_record(
                    release_id="nightly-2026-08-20",
                    version=version,
                    commit="0123456789abcdef0123456789abcdef01234567",
                    published_at="2026-08-20T08:30:00Z",
                    workflow_url="https://github.com/ranvier-labs/lean4-cuda-backend/actions/runs/1",
                    cuda_toolkit_version="13.0.88",
                    ptx_architecture="compute_90",
                    registered=1,
                    failures=0,
                    skipped=0,
                    umbrella_modules=1,
                    linux_archive=linux_archive,
                    linux_manifest=linux_manifest,
                    linux_aarch64_archive=arm_archive,
                    linux_aarch64_manifest=arm_manifest,
                )


class SiteGenerationTests(unittest.TestCase):
    def test_agent_docs_disclose_elan_checksum_boundary(self) -> None:
        for path in (ROOT / "site" / "llms.txt", ROOT / "site" / "agent-install.md"):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("does not", text)
                self.assertIn("checksum", text)

    def test_empty_channel_has_nullable_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = root / "records"
            static = root / "static"
            output = root / "output"
            records.mkdir()
            shutil.copytree(ROOT / "site", static)
            self.assertEqual(build_site(records, static, output, ROOT / "schema"), 0)
            latest = json.loads(
                (output / "releases" / "v1" / "latest.json").read_text(encoding="utf-8")
            )
            self.assertIsNone(latest["release"])
            self.assertIn("No public nightly yet", (output / "index.html").read_text(encoding="utf-8"))
            self.assertTrue((output / "schema" / "release-v1.schema.json").is_file())
            collector = LinkCollector()
            collector.feed((output / "index.html").read_text(encoding="utf-8"))
            for link in collector.links:
                if link.startswith(("https://", "http://", "#")):
                    continue
                with self.subTest(link=link):
                    self.assertTrue((output / link).is_file())

    def test_release_record_becomes_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = root / "records"
            static = root / "static"
            output = root / "output"
            records.mkdir()
            shutil.copy(FIXTURE, records / FIXTURE.name)
            shutil.copytree(ROOT / "site", static)
            self.assertEqual(len(load_release_records(records)), 1)
            self.assertEqual(build_site(records, static, output, ROOT / "schema"), 1)
            latest = json.loads(
                (output / "releases" / "v1" / "latest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(latest["release"]["id"], "nightly-2026-08-12")
            self.assertEqual(latest["release"]["metadataUrl"], "./nightly-2026-08-12.json")
            self.assertTrue(
                (output / "releases" / "v1" / "nightly-2026-08-12.json").is_file()
            )

    def test_schema_files_are_json(self) -> None:
        for path in sorted((ROOT / "schema").glob("*.json")):
            with self.subTest(path=path):
                self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_guide_pages_are_copied_and_linked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = root / "records"
            static = root / "static"
            output = root / "output"
            records.mkdir()
            shutil.copytree(ROOT / "site", static)
            self.assertEqual(build_site(records, static, output, ROOT / "schema"), 0)
            for relative in (
                "docs/index.html",
                "docs/kernels.html",
                "docs/runtime.html",
                "install.html",
            ):
                path = output / relative
                with self.subTest(relative=relative):
                    self.assertTrue(path.is_file())
                    text = path.read_text(encoding="utf-8")
                    self.assertIn("lean cuda", text)
            landing = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn("docs/index.html", landing)
            self.assertIn("@[cuda_kernel]", landing)
            llms = (output / "llms.txt").read_text(encoding="utf-8")
            self.assertIn("docs/index.html", llms)
            collector = LinkCollector()
            collector.feed((output / "docs/index.html").read_text(encoding="utf-8"))
            for link in collector.links:
                if link.startswith(("https://", "http://", "#")):
                    continue
                resolved = (output / "docs" / link).resolve()
                self.assertTrue(resolved.is_file(), msg=link)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.api_docs import (
    ApiDocsError,
    REQUIRED_PAGES,
    audit_docs,
    compare_module_manifests,
    publish_docs,
)


class ApiDocsTests(unittest.TestCase):
    def write_manifest(self, path: Path, modules: dict[str, str]) -> None:
        path.write_text(
            json.dumps(
                {
                    "schema": "lean.cuda.release-manifest/v1",
                    "fileCount": len(modules),
                    "files": [
                        {
                            "path": name,
                            "sha256": digest,
                            "size": 1,
                            "type": "file",
                        }
                        for name, digest in modules.items()
                    ],
                }
            ),
            encoding="utf-8",
        )

    def write_docs(self, root: Path) -> None:
        for relative in REQUIRED_PAGES:
            page = root / relative
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text("<html><body>API</body></html>\n", encoding="utf-8")
        declarations = root / "declarations" / "module.bmp"
        declarations.parent.mkdir(parents=True)
        declarations.write_text(
            json.dumps({"declarations": [{"sourceLink": ""}]}), encoding="utf-8"
        )

    def test_identical_architecture_modules_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            modules = {
                "lib/lean/Lean/Compiler.olean": "a" * 64,
                "lib/lean/Lean/Cuda.ilean": "b" * 64,
            }
            self.write_manifest(root / "x86.json", modules)
            self.write_manifest(root / "arm.json", modules)
            self.assertEqual(
                compare_module_manifests(root / "x86.json", root / "arm.json"), 2
            )

    def test_architecture_module_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_manifest(
                root / "x86.json", {"lib/lean/Lean/Cuda.olean": "a" * 64}
            )
            self.write_manifest(
                root / "arm.json", {"lib/lean/Lean/Cuda.olean": "b" * 64}
            )
            with self.assertRaisesRegex(ApiDocsError, "differ across architectures"):
                compare_module_manifests(root / "x86.json", root / "arm.json")

    def test_source_safe_documentation_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_docs(root)
            result = audit_docs(root)
            self.assertGreater(result["files"], len(REQUIRED_PAGES))

    def test_private_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_docs(root)
            (root / REQUIRED_PAGES[0]).write_text("/home/private/source.lean")
            with self.assertRaisesRegex(ApiDocsError, "forbidden publication content"):
                audit_docs(root)

    def test_nonempty_source_link_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_docs(root)
            (root / "declarations" / "module.bmp").write_text(
                json.dumps({"sourceLink": "https://example.com/source"}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ApiDocsError, "non-empty source link"):
                audit_docs(root)

    def test_broken_local_link_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_docs(root)
            (root / REQUIRED_PAGES[0]).write_text(
                '<html><body><a href="../omitted.html">omitted</a></body></html>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ApiDocsError, "broken local link"):
                audit_docs(root)

    def test_publish_creates_both_architecture_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docs = root / "build" / "doc"
            self.write_docs(docs)
            (docs / "api-docs.json").write_text(
                json.dumps(
                    {
                        "schema": "lean.cuda.api-docs/v1",
                        "releaseId": "nightly-2026-08-22",
                        "version": "4.33.0-test",
                        "compiledModuleCount": 2,
                    }
                ),
                encoding="utf-8",
            )
            site = root / "site"
            publish_docs(root / "build", site)
            for architecture in ("x86_64", "aarch64"):
                self.assertTrue(
                    (site / "api" / "nightly-2026-08-22" / architecture / REQUIRED_PAGES[0]).is_file()
                )
                self.assertTrue((site / "api" / architecture / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()

import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


BUILDER_PATH = Path(__file__).resolve().parents[1] / "tools" / "create_publication_data_archive.py"
spec = importlib.util.spec_from_file_location("publication_archive", BUILDER_PATH)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PublicationArchiveTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.metadata = {
            **builder.METADATA,
            "release_version": "2",
            "dataset_doi": "10.1234/test-dataset.v2",
            "code_release_doi": "10.1234/test-workflow.v2",
            "article_doi": "10.1234/test-paper",
            "code_repo_url": "https://example.org/test-workflow.git",
            "dataset_concept_doi": "10.1234/test-dataset",
            "code_concept_doi": "10.1234/test-workflow",
        }
        for name, value in [("PROJECT_ROOT", self.root), ("METADATA", self.metadata)]:
            override = patch.object(builder, name, value)
            override.start()
            self.addCleanup(override.stop)
        self.members = [entry["path"] for entry in builder.publication_members()]
        for name in self.members:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"Fixture for {name}\n".encode())
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def build(self, output=None, draft=False):
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            return builder.build_archive(output, draft)

    def test_release_metadata_and_checksums_are_consistent(self):
        self.assertEqual(self.build(), 0)
        output = self.root / "resources/downloads/publication_data_v2.zip"
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read("publication_data_manifest.json"))
            readme = archive.read("README.md").decode()
            changelog = archive.read("CHANGELOG.md").decode()
            for key, value in self.metadata.items():
                self.assertEqual(manifest[key], value)
                if key not in ("dataset_concept_doi", "code_concept_doi"):
                    self.assertIn(value, readme)
            self.assertNotIn("Dataset concept DOI:", readme)
            self.assertNotIn("Workflow concept DOI:", readme)
            self.assertIn(f"with DOI {self.metadata['code_release_doi']}.", readme)
            self.assertIn(f"## v2 - {manifest['created_at'].split('T')[0]}", changelog)
            self.assertNotIn("release_date", manifest)
            self.assertNotIn("Release date:", readme)
            self.assertNotIn("publication_status", manifest)
            self.assertNotIn("Status:", readme)
            self.assertNotIn("candidate", readme.lower())
            self.assertNotIn("pending publication", changelog)
            self.assertEqual(sum(line.startswith("## ") for line in changelog.splitlines()), 2)
            self.assertIn("## v1 - 2026-05-29\n\nInitial release.", changelog)
            self.assertIn("`fig02__geometry_sketch.png`", changelog)
            self.assertNotIn("fig03__geometry_sketch.png", changelog)
            self.assertNotIn("TODO", changelog)
            self.assertIn(f"git clone {self.metadata['code_repo_url']} cryoswath_paper_workflow", readme)
            self.assertNotIn("Membership is explicit", readme)
            self.assertEqual(set(manifest["required_members"]), set(self.members))
            self.assertEqual(manifest["missing_members"], [])
            docs = {"README.md", "CHANGELOG.md", "LICENSE.txt", "publication_data_manifest.json", "SHA256SUMS"}
            self.assertEqual(set(archive.namelist()), set(self.members) | docs)
            for line in archive.read("SHA256SUMS").decode().splitlines():
                digest, name = line.split(maxsplit=1)
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
            for entry in manifest["files"]:
                self.assertEqual(len(archive.read(entry["path"])), entry["size_bytes"])
                self.assertEqual(hashlib.sha256(archive.read(entry["path"])).hexdigest(), entry["sha256"])
        self.assertEqual(self.stderr.getvalue(), "")
        self.assertNotIn("DRAFT", self.stdout.getvalue())

    def test_missing_required_metadata_does_not_replace_an_output(self):
        output = self.root / "release.zip"
        output.write_bytes(b"existing release")
        for key in ("release_version", "dataset_doi"):
            with self.subTest(key=key), patch.dict(self.metadata, {key: ""}):
                self.assertEqual(self.build(output), 1)
                self.assertEqual(output.read_bytes(), b"existing release")
                self.assertIn(key, self.stderr.getvalue())

    def test_manifest_and_changelog_share_one_utc_build_timestamp(self):
        built_at = datetime(2030, 2, 3, 23, 59, 59, tzinfo=timezone.utc)
        with patch.object(builder, "datetime") as clock:
            clock.now.return_value = built_at
            clock.fromisoformat.side_effect = datetime.fromisoformat
            self.assertEqual(self.build(), 0)
            clock.now.assert_called_once_with(timezone.utc)
        with zipfile.ZipFile(self.root / "resources/downloads/publication_data_v2.zip") as archive:
            manifest = json.loads(archive.read("publication_data_manifest.json"))
            self.assertEqual(manifest["created_at"], "2030-02-03T23:59:59Z")
            self.assertIn("## v2 - 2030-02-03", archive.read("CHANGELOG.md").decode())

    def test_optional_dois_remind_and_fall_back_to_concept(self):
        self.metadata.update(code_release_doi="", article_doi="")
        output = self.root / "custom-name.zip"
        self.assertEqual(self.build(output), 0)
        self.assertIn("code_release_doi", self.stderr.getvalue())
        self.assertIn("article_doi", self.stderr.getvalue())
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read("publication_data_manifest.json"))
            readme = archive.read("README.md").decode()
            self.assertEqual(manifest["code_release_doi"], "")
            self.assertIn(f"Workflow concept DOI: {self.metadata['code_concept_doi']}", readme)
            self.assertIn(f"with DOI {self.metadata['code_concept_doi']}.", readme)
            self.assertNotIn("Dataset concept DOI:", readme)
            self.assertNotIn("Previous workflow release DOI:", readme)
            self.assertNotIn("Workflow release DOI:", readme)

    def test_explicit_draft_allows_unfilled_metadata_and_missing_member(self):
        for key in ("release_version", "dataset_doi"):
            self.metadata[key] = ""
        missing = self.members[0]
        (self.root / missing).unlink()
        self.assertEqual(self.build(draft=True), 0)
        with zipfile.ZipFile(self.root / "resources/downloads/publication_data_draft.zip") as archive:
            manifest = json.loads(archive.read("publication_data_manifest.json"))
            self.assertEqual(manifest["publication_status"], "draft")
            self.assertEqual(manifest["missing_members"], [missing])
            self.assertIn(missing, manifest["required_members"])
            self.assertIn("Status: DRAFT", archive.read("README.md").decode())
            self.assertIn("Dataset concept DOI:", archive.read("README.md").decode())
        self.assertIn("Wrote DRAFT", self.stdout.getvalue())

    def test_empty_optional_repository_url_omits_clone_instructions(self):
        self.metadata["code_repo_url"] = ""
        self.assertEqual(self.build(), 0)
        with zipfile.ZipFile(self.root / "resources/downloads/publication_data_v2.zip") as archive:
            readme = archive.read("README.md").decode()
            self.assertNotIn("git clone", readme)
            self.assertNotIn("You can obtain a copy", readme)
            manifest = json.loads(archive.read("publication_data_manifest.json"))
            self.assertEqual(manifest["code_repo_url"], "")

    def test_missing_member_fails_normal_build(self):
        (self.root / self.members[0]).unlink()
        self.assertEqual(self.build(), 1)
        self.assertIn(self.members[0], self.stderr.getvalue())
        self.assertFalse((self.root / "resources/downloads").exists())

    def test_original_archive_and_its_alias_are_protected(self):
        original = self.root / "resources/downloads/publication_data.zip"
        original.parent.mkdir(exist_ok=True)
        original.write_bytes(b"original release")
        alias = self.root / "alias.zip"
        alias.hardlink_to(original)
        for output in [original, alias]:
            with self.subTest(output=output):
                self.assertEqual(self.build(output), 1)
                self.assertEqual(original.read_bytes(), b"original release")

    def test_failed_checksum_validation_preserves_previous_archive(self):
        output = self.root / "release.zip"
        output.write_bytes(b"previous release")
        with patch.object(builder, "sha256_file", return_value="0" * 64):
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                self.build(output)
        self.assertEqual(output.read_bytes(), b"previous release")
        self.assertEqual(list(self.root.glob("*.tmp")), [])
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

    def test_cli_keeps_default_selection_and_output_override(self):
        with patch("sys.argv", [str(BUILDER_PATH)]):
            args = builder.parse_args()
            self.assertIsNone(args.output)
            self.assertFalse(args.allow_missing)
        with patch("sys.argv", [str(BUILDER_PATH), "--output", "custom.zip", "--allow-missing"]):
            args = builder.parse_args()
            self.assertEqual(args.output, Path("custom.zip"))
            self.assertTrue(args.allow_missing)


if __name__ == "__main__":
    unittest.main()

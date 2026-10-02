"""Regresiones stdlib para containment y ownership de inspection spaces."""

import tempfile
import unittest
from pathlib import Path

from inspection.space_access import (SpaceAccessError, claim_space, read_claim,
                                     space_dir, validate_space_id)


class SpaceAccessSecurityTest(unittest.TestCase):
    def test_rejects_traversal_and_ambiguous_ids(self):
        for value in ("", ".", "..", "../escape", "a/b", r"a\b", "/tmp/x",
                      "a.b", "a:b", "x" * 129):
            with self.subTest(value=value), self.assertRaises(SpaceAccessError):
                validate_space_id(value)

    def test_rejects_safe_looking_symlink(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            root = Path(td)
            (root / "safe-id").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(SpaceAccessError):
                space_dir(root, "safe-id", create=True)

    def test_claim_is_immutable_and_private_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            first = claim_space(td, "inspect-abc", owner_id="user-a")
            self.assertEqual(first, read_claim(td, "inspect-abc"))
            self.assertFalse(first["public"])
            with self.assertRaises(SpaceAccessError):
                claim_space(td, "inspect-abc", owner_id="user-b")
            with self.assertRaises(SpaceAccessError):
                claim_space(td, "inspect-abc", public=True)

    def test_public_requires_explicit_claim_and_refuses_legacy_adoption(self):
        with tempfile.TemporaryDirectory() as td:
            directory = space_dir(td, "demo-space", create=True)
            self.assertIsNone(read_claim(td, "demo-space"))
            (directory / "events.jsonl").write_text("private history\n", encoding="utf-8")
            with self.assertRaises(SpaceAccessError):
                claim_space(td, "demo-space", public=True)
            claim = claim_space(td, "new-public-space", public=True)
            self.assertTrue(claim["public"])
            self.assertEqual(claim, read_claim(td, "new-public-space"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from scripts.check_commit_messages import validate_message


class CommitMessageTests(unittest.TestCase):
    def test_chore_subject_is_valid(self) -> None:
        self.assertEqual(validate_message("chore: update Pages actions\n"), [])

    def test_feature_with_changelog_body_is_valid(self) -> None:
        message = (
            "feat: publish immutable nightly metadata\n\n"
            "This PR publishes the accepted dual-architecture release record.\n"
        )
        self.assertEqual(validate_message(message), [])

    def test_unknown_type_is_rejected(self) -> None:
        self.assertRegex(validate_message("build: update actions\n")[0], "subject must match")

    def test_capitalized_subject_is_rejected(self) -> None:
        self.assertIn(
            "subject must begin with a lowercase letter",
            validate_message("doc: Explain installation\n"),
        )

    def test_subject_period_is_rejected(self) -> None:
        self.assertIn(
            "subject must not end with a period",
            validate_message("test: cover release metadata.\n"),
        )

    def test_feature_without_body_is_rejected(self) -> None:
        self.assertIn(
            "feat commits require a body beginning with 'This PR '",
            validate_message("feat: add nightly channel\n"),
        )

    def test_fix_body_must_start_with_this_pr(self) -> None:
        self.assertIn(
            "fix commit body must begin with 'This PR '",
            validate_message("fix: reject mutable URLs\n\nReject mutable URLs.\n"),
        )

    def test_body_requires_blank_line(self) -> None:
        self.assertIn(
            "body must be separated from the subject by a blank line",
            validate_message("doc: explain channel\nExplain it.\n"),
        )


if __name__ == "__main__":
    unittest.main()

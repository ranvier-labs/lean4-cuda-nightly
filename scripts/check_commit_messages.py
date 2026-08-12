#!/usr/bin/env python3
"""Check Git commit messages against the Lean 4 commit convention."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys


ALLOWED_TYPES = ("feat", "fix", "doc", "style", "refactor", "test", "chore", "perf")
SUBJECT_RE = re.compile(rf"^({'|'.join(ALLOWED_TYPES)}): (.+)$")


class CommitMessageError(Exception):
    """A commit message violates the repository convention."""


def validate_message(message: str) -> list[str]:
    """Return every convention error in one commit message."""
    lines = message.rstrip("\n").splitlines()
    if not lines:
        return ["message is empty"]

    subject = lines[0]
    match = SUBJECT_RE.fullmatch(subject)
    if match is None:
        return [
            "subject must match '<type>: <subject>' with type one of "
            + ", ".join(ALLOWED_TYPES)
        ]

    commit_type, text = match.groups()
    errors: list[str] = []
    first_letter = next((character for character in text if character.isalpha()), None)
    if first_letter is not None and first_letter.isupper():
        errors.append("subject must begin with a lowercase letter")
    if text.endswith("."):
        errors.append("subject must not end with a period")

    body_lines = lines[1:]
    has_body = any(line.strip() for line in body_lines)
    if has_body and (not body_lines or body_lines[0] != ""):
        errors.append("body must be separated from the subject by a blank line")

    if commit_type in {"feat", "fix"}:
        if not has_body:
            errors.append(f"{commit_type} commits require a body beginning with 'This PR '")
        else:
            first_body_line = next((line for line in body_lines if line.strip()), "")
            if not first_body_line.startswith("This PR "):
                errors.append(f"{commit_type} commit body must begin with 'This PR '")
    return errors


def git(command: list[str]) -> str:
    result = subprocess.run(
        ["git", *command],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CommitMessageError(f"git {' '.join(command)} failed: {detail}")
    return result.stdout


def commits_in(revision: str) -> list[str]:
    commits = git(["rev-list", "--reverse", revision]).splitlines()
    if not commits:
        raise CommitMessageError(f"revision {revision!r} selects no commits")
    return commits


def check_revision(revision: str) -> int:
    failures = 0
    commits = commits_in(revision)
    for commit in commits:
        message = git(["show", "-s", "--format=%B", commit])
        errors = validate_message(message)
        if not errors:
            continue
        failures += 1
        subject = message.splitlines()[0] if message.splitlines() else "<empty>"
        print(f"{commit} {subject}", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
    if failures:
        print(
            f"error: {failures} of {len(commits)} commit message(s) violate the Lean 4 convention",
            file=sys.stderr,
        )
        return 1
    print(f"validated {len(commits)} commit message(s) in {revision}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("revision", nargs="?", default="HEAD")
    arguments = parser.parse_args(argv)
    try:
        return check_revision(arguments.revision)
    except CommitMessageError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

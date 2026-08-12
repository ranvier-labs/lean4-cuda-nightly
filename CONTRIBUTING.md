# Contributing

This repository follows Lean 4's commit and pull-request convention.

## Commit messages

Use:

```text
<type>: <subject>

<body>

<footer>
```

The accepted types are:

- `feat` — a feature;
- `fix` — a bug fix;
- `doc` — documentation;
- `style` — formatting with no semantic change;
- `refactor` — a code change that is neither a feature nor a fix;
- `test` — missing or changed tests;
- `chore` — repository and automation maintenance;
- `perf` — a performance improvement.

Write the subject in imperative present tense, begin it with a lowercase letter, and omit a final
period. When a body is present, separate it from the subject with one blank line and explain the
motivation as well as the behavior change.

Every `feat` or `fix` commit must have a body whose first paragraph begins with `This PR `. The
corresponding pull request must carry an appropriate `changelog-*` label. Pull-request titles use
the same `<type>: <subject>` format because squash merging makes the title the final commit
subject.

Examples:

```text
feat: publish immutable nightly metadata

This PR publishes the accepted dual-architecture release record and updates the generated channel
index.
```

```text
chore: update Pages actions
```

CI runs `scripts/check_commit_messages.py` over every commit introduced by a push or pull request.

## Validation

Run before pushing:

```bash
make check
git diff --check
```

When changing the release contract, update its JSON schema, semantic validator, fixtures,
documentation, agent instructions, and tests together.

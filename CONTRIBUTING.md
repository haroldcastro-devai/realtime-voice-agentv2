# Contributing

Chat with Harold may be in Spanish. **Code, docs, Jira issues, GitHub issues, pull requests, and review comments are English.**

This is a public MIT portfolio repo (fictional **Acme Telco** / agent **Ava**). Do not add employer, carrier, customer, or secret data. Runtime settings use the `RVA_*` prefix.

## One change, one trail

One Jira issue = one git branch = one pull request.

| Step | Rule |
|------|------|
| Issue | Work from a NAT ticket. Move it to in progress when you start. |
| Branch | `feat/NAT-<n>-<short-description>` (use `fix/` or `docs/` when that fits). |
| Commits | Conventional, small: `NAT-<n> feat\|fix\|docs\|test\|chore: …` |
| PR title | `NAT-<n>: …` with a link to the Jira issue |
| Merge | **Rebase and merge** only. Never merge your own PR. Never push to `main`. Never force-push `main`. |

Intended Jira flow: To Do → In Progress → In Review → Done.

- In Review requires an open PR linked on the issue.
- Done requires that PR to be merged.
- This board may show Spanish names (`Por hacer`, `En curso`, `Listo`) and may not have In Review yet; still do not mark Done until merge.

## Before you open a PR

From the repo root, with the `dev` extra installed:

```bash
pytest
ruff check src tests scripts
ruff format --check src tests scripts
python scripts/check_clean.py
```

CI runs the same gates (`pytest` on 3.10 and 3.12, `ruff`, `check_clean`). A red job means the PR is not ready.

## Review

The author does not approve or merge their own PR. A **code-reviewer** looks at the diff in a **separate session** and leaves comments. Harold Castro reads the diff and gives the **final approval**, then rebase-and-merge.

Do not invent review comments, approvals, or LGTM.

## Signatures

GitHub and Jira comments, and the pull request body, end with a role line. They must not use tool banners, product footers, or `Co-authored-by` lines for coding assistants.

Implementer (PR body and comments):

```
— Harold Castro
```

Reviewer (GitHub review summary, event COMMENT only — never Approve):

```
— code-reviewer (separate session). Does not approve or merge. Final approval: Harold Castro.
```

Author/committer identity is **Harold Castro** with the GitHub noreply address for this account.

## License

MIT, Copyright (c) 2026 Harold Castro.

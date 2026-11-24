Personal administration, openQA, OBS/openSUSE, Git, and system utility scripts.

## Overview

This repository contains CLI tools, workflow helpers, and maintenance scripts.

Key areas include:

- **Git and code review automation**: Tools for GitHub/GitLab PR triage, automated bot
  reviews, cleanup, branch rebasing, and signing (`review-bot-batch`, `gh-pr-triage`,
  `gh-as-bot`, `glab-as-bot`, `gitea-review-cleanup`, `git-sign-and-push`). `gh-as-bot` and
  `glab-as-bot` refuse forge writes unless `REVIEW_BOT_POST=1` is set; `review-bot-batch`
  sets it for live runs and leaves it unset for `--dry-run`.
- **openQA and Open Build Service (OBS)**: Diagnostics and synchronization tools for OBS
  staging projects, dependency synchronization, and openQA investigations (`obs-pr-repair`,
  `osc-sync-leap`, `osc-sync-deps`, `osc-get-pr-status`, `suse-qa-sle-etherpad-status`).
- **System administration and utilities**: Network helpers, backup utilities, desktop
  adjustments, and hardware monitoring scripts.

## Highlighted tools

### git-worktree-audit

Project-agnostic pre-consolidation check: reports checkouts that hold branches or
remote-tracking refs whose tip object the primary checkout does not have. Exits 1 when
anything is at risk, so it can gate moving or removing a checkout.

```bash
# Audit a deep clone before retiring it into worktrees of the primary checkout
git worktree-audit --primary ~/local/os-autoinst/openQA ~/local/os-autoinst/oqa4

# Machine-readable, including ahead/behind and dirty counts
git worktree-audit --json --primary ~/local/os-autoinst/openQA archive/oqa4-20261120
```

Adopt at-risk refs locally before removing the checkout:

```bash
git -C primary fetch --no-tags /path/to/clone '+refs/heads/*:refs/remotes/clones/clone/*'
git -C primary fetch --no-tags /path/to/clone '+refs/remotes/*:refs/remotes/clones/clone/*'
```

### obs-pr-repair

Project-agnostic OBS PR diagnostics and recovery tool for GitHub repositories
utilizing `.obs/workflows.yml` (e.g. openQA, os-autoinst, os-autoinst-scripts).

#### Usage

```bash
# Check current PR project from within git repository checkout:
obs-pr-repair

# Check specific PR in openQA:
obs-pr-repair --repo os-autoinst/openQA --pr 7968

# Recreate broken project (delete OBS project and cycle PR):
obs-pr-repair --recreate --pr 7968

# Non-interactive recreate:
obs-pr-repair --recreate --pr 7968 --yes

# Force-repair unbranched package:
obs-pr-repair --repair-branch --pr 7968

# Trigger rebuild of healthy project:
obs-pr-repair --rebuild --pr 7968
```

## Development and testing

Python dependencies and virtual environments are managed using [uv](https://github.com/astral-sh/uv).

### Running tests

Run tests and checks via `make`:

```bash
# Run all unit tests with coverage and static analysis
make test

# Run unit tests only
make test-unit

# Run fast unit tests without coverage
make test-unit-no-coverage
```

### Static analysis and style checks

```bash
# Fast style and static analysis (ruff, shellcheck, banned patterns, lockfile)
make checkstyle

# Run type checker (ty)
make check-types

# Automatically format code and apply lint fixes
make tidy
```

## License

MIT License. See [LICENSE](LICENSE) for details.

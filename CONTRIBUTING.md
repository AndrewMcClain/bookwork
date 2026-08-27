# Contributing to Bookwork

## Getting set up

```bash
uv sync
git config core.hooksPath .githooks
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

The two `git config` lines are per-clone and worth doing: the first checks
your commit messages before they land, the second keeps `git blame` from
attributing everything to a bulk reformat.

## Before you push

```bash
uv run ruff format src tests
uv run ruff check src tests
uv run pytest
```

With no display attached (CI, an SSH session), prefix pytest with
`QT_QPA_PLATFORM=offscreen`.

## Read the docs first

[docs/decisions.md](docs/decisions.md) records choices that are not obvious
from the code, and the bugs that motivated them. Several things here look odd
until you know why — printing deliberately shrinks pages, the last signature
is deliberately not padded to full, presets deliberately derive their field
list. Check there before "fixing" something that looks wrong.

If you make a call a future reader would otherwise have to rediscover, add an
entry saying what you decided, why, and what broke.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/), because the
version number and changelog are derived from them:

```
type(optional scope): short summary

Longer body explaining why, what broke, what you verified.
```

| Type | Use for | Version effect |
|---|---|---|
| `feat` | new capability | minor |
| `fix` | bug fix | patch |
| `perf` | faster, same behaviour | patch |
| `refactor` | restructuring, no behaviour change | none |
| `test`, `docs`, `style`, `build`, `ci`, `chore` | as named | none |

A breaking change is `feat!:` or a `BREAKING CHANGE:` footer.

**Only the subject line is constrained.** Bodies in this repo are long and
specific on purpose — what was measured, what was ruled out, what the failure
looked like. Keep writing those; the prefix just makes the subject
machine-readable.

The hook is bypassable with `--no-verify`. That is on purpose: it is a
convenience, not a gate.

## Releasing

```bash
uv run cz bump
```

That reads the commits since the last tag, works out the version bump, updates
`pyproject.toml`, writes `CHANGELOG.md` and tags. Push with `git push --follow-tags`.

The project is pre-1.0, so `major_version_zero` is set: a breaking change
bumps the minor rather than jumping to 1.0. Drop that setting once the
imposition parameters and preset format are considered stable.

Commits before `580efa6` predate this convention and are excluded from the
changelog.

## What is worth working on

[README's Known gaps](README.md#known-gaps) is the honest list. The biggest is
that Windows and macOS builds have never been run — CI on hosted runners is
the intended fix.

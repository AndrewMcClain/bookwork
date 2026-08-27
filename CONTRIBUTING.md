# Contributing

Questions and half-finished PRs are welcome. This is here to save you a wasted
afternoon, not to gate you.

## Setup

```bash
uv sync
git config core.hooksPath .githooks            # checks commit messages
git config blame.ignoreRevsFile .git-blame-ignore-revs   # skips the bulk reformat
```

Both git config lines are per-clone; git can't version them for you.

## Before you push

```bash
uv run ruff format src tests
uv run ruff check src tests
uv run pytest          # QT_QPA_PLATFORM=offscreen if there's no display
```

**There is no CI**, so these are the only checks that happen.

## Before you change anything

Read [docs/decisions.md](docs/decisions.md). Several things look like mistakes
until you know why — printing deliberately shrinks pages, the last signature is
deliberately not padded full, presets derive their field list. If you change
something it describes, update it in the same commit.

## Proposing a change

Open an issue first for anything substantial; a maintainer's opinion is often
the deciding factor and it's better to hear it before you've written it.
Obvious fixes can go straight to a PR.

- One change per PR.
- Work on a branch, not your fork's `main`.
- Contribute code you understand — see [AI](#ai).

## Tests

Every behaviour change needs one. This tool wastes paper when it's wrong.

**Check your test fails without your fix.** Two bugs here were "covered" by
tests that passed either way: one round-tripped a preset inside a single
process, hitting an in-memory cache instead of the broken path; another
compared renders using PDFs so symmetric that a mirrored page barely moved a
pixel.

Geometry lives in pure functions so most of it needs no window. An autouse
fixture forces animations to zero duration — without it tests race the
animation. Tests may assert freely and reach into private helpers.

## AI

Most of this repo was written with an AI assistant and the commits say so, so
forbidding it in yours would be absurd. The bar is the same either way: **you
understand it, you verified it, and it's yours to contribute** under GPL
v3-or-later. (Whether generated text carries copyright is unsettled; opening a
PR asserts the contribution is yours to give.)

That bar is harder to clear for generated code, because the failure mode is
code that *looks* right — both test examples above were AI-written, and neither
was caught by reading the diff.

Add a `Co-Authored-By:` trailer. Provenance, not a warning label.

## Reporting a bug

This produces physical output, so the useful details are unusual:

- **Wrong on screen, or wrong on paper?** Different causes entirely.
- **Printer make, model, driver.** Three bugs here were printer-specific;
  without it a report often isn't actionable.
- **Imposition settings**, or the preset name.
- **OS**, and source vs packaged build.
- **The document's shape** — page count, page size, uniform or not. Please
  don't send the PDF; manuscripts are private and the bugs are about geometry.
  A minimal PDF that reproduces it beats the original anyway.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/) — the version and
changelog derive from them.

`feat` minor · `fix`/`perf` patch · `refactor`/`test`/`docs`/`style`/`build`/`ci`/`chore` none ·
`feat!` or a `BREAKING CHANGE:` footer for breaking.

**Only the subject is constrained.** Bodies here are long on purpose — what was
measured, what was ruled out, what the failure looked like. Keep writing those.
The hook is bypassable with `--no-verify`; it's a convenience, not a gate.

## Releasing

```bash
uv run cz bump && git push --follow-tags
```

Derives the bump from commits, updates the version, writes `CHANGELOG.md`,
tags. Pre-1.0, so `major_version_zero` makes a breaking change bump the minor;
drop it once the parameters and preset format settle.

## Worth working on

[README's Known gaps](README.md#known-gaps). The big one: Windows and macOS
builds have never been run.

## Licence

GPL v3-or-later; contributions under the same. New files need the header the
existing ones carry — copy it from any file in `src/`. Check
[docs/third-party.md](docs/third-party.md) before adding a dependency;
compatibility isn't automatic in a GPL project.

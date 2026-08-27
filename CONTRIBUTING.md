# Contributing to Bookwork

Questions, half-finished pull requests and "is this even the right approach?"
are all welcome. Everything below is here to save you a wasted afternoon, not
to be a barrier.

## Getting set up

```bash
uv sync
git config core.hooksPath .githooks
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

Both `git config` lines are per-clone, and git cannot version them for you.
The first checks your commit messages before they land; the second stops
`git blame` attributing everything to a bulk reformat.

Run the app from source with:

```bash
uv run bookwork [path/to/file.pdf]
```

## Before you push

```bash
uv run ruff format src tests
uv run ruff check src tests
uv run pytest
```

**There is no CI yet**, so these are the only checks that happen. Please
actually run them.

With no display attached (an SSH session, a container), prefix pytest with
`QT_QPA_PLATFORM=offscreen`.

## Read docs/decisions.md first

[docs/decisions.md](docs/decisions.md) records choices that are not obvious
from the code, and the bugs that motivated them. Several things here look like
mistakes until you know why:

- printing deliberately shrinks each sheet rather than printing at full size
- the last signature is deliberately *not* padded to a full signature
- presets derive their field list instead of naming the fields
- the bound preview crops from imposed sheets rather than re-rendering

If you change something that file describes, update the description in the
same commit. If you make a call a future reader would otherwise have to
rediscover, add an entry: what you decided, why, and what broke.

## Proposing a change

Open an issue or discussion before starting anything substantial. This is a
small project and a maintainer's opinion is often the deciding factor — better
to find that out before you have written it. Obvious bug fixes can go straight
to a PR.

- **One change per pull request.** Two unrelated fixes are two PRs.
- **Work on a branch**, not your fork's `main` — otherwise syncing your fork
  later becomes miserable.
- **Contribute code you understand.** If you cannot explain why a change works,
  it is not ready, whoever or whatever wrote it — see
  [Using AI assistance](#using-ai-assistance).

## Tests

Every behaviour change needs a test. The suite is thorough on purpose: this
tool wastes paper and ink when it is wrong, and several bugs here were subtle
enough that only a test caught them.

**Check your test fails without your fix.** This is not a formality — two bugs
in this repo were "covered" by tests that passed either way. One saved and
reloaded a preset inside a single process, so it hit an in-memory cache and
never exercised the real code path. Another compared rendered images using test
PDFs so nearly symmetric that a horizontally mirrored page barely changed the
pixels. Both tests looked fine and proved nothing.

Conventions worth knowing:

- Geometry lives in module-level pure functions taking plain numbers, so most
  of it is testable without a window or a running animation.
- An autouse fixture forces page-turn animations to zero duration. Without it,
  tests assert against a widget mid-animation and can tear it down while an
  animation is still driving it.
- Printing is tested by pointing a `QPrinter` at a PDF file, which exercises
  the same painter path a real job takes.
- Tests may assert freely and may reach into private helpers; both are the
  point, and ruff is configured to allow it under `tests/`.

## Using AI assistance

Yes, and it would be odd to pretend otherwise: most of this repository was
written with an AI assistant, and the commits say so — 29 of the first 33 carry
a `Co-Authored-By` trailer. A project whose own history is full of AI-assisted
work is in no position to forbid it in yours.

So the rule is not about the tool. It is the same bar every contribution meets:

- **You understand it.** You can explain why it works, and what would break it.
- **You verified it.** Tests that actually fail without your change; for
  anything about printing or layout, output you have looked at.
- **You have the right to contribute it** under GPL v3-or-later. Whether
  machine-generated text carries copyright is unsettled, and this project
  cannot resolve that for you — but by opening a PR you are asserting the
  contribution is yours to give.

That bar is not boilerplate, and it is stricter in practice for generated code,
because the failure mode is code that *looks* right. Real examples from this
repository, all AI-written and all caught by verification rather than by
review:

- A test compared rendered images to prove a page was not mirrored — using test
  PDFs so nearly symmetric that mirroring one barely moved a pixel. It passed
  whether the bug was present or not.
- A preset round-trip test saved and loaded within a single process, so it hit
  an in-memory cache and never touched the code path where the bug actually
  lived. Presets were broken across every restart and the test was green.
- A duplicated branch was removed as redundant. It was redundant — because both
  halves were doing the same wrong thing.

None of those were caught by reading the diff. They were caught by asking
whether the test failed without the fix, and by looking at the output.

If you use an assistant, add the trailer:

```
Co-Authored-By: <assistant name> <email or noreply address>
```

Not as a warning label — as provenance, the same reason human co-authors get
one.

## Reporting a bug

Bookwork produces physical output, so the useful details are unusual. Please
include:

- **Whether it is wrong on screen or wrong on paper.** These have completely
  different causes, and it is the first thing anyone will ask.
- **Your printer make and model, and the driver.** Three separate bugs in this
  project were printer-specific — landscape pages printing portrait, content
  clipped at the edges, and folds landing off centre. A report without the
  printer is often not actionable.
- **The imposition settings**, or the preset name — signature size, sheet size,
  margin, gutter, and which of the cover/endpaper/padding boxes were ticked.
- **Your OS**, and whether you are running from source or a packaged build.
- **The document's shape** — page count, page size, and whether every page is
  the same size. Please don't send the PDF: manuscripts are usually private,
  and nearly every bug here turns on counts and geometry rather than content.
  If some document reproduces something those details don't explain, a minimal
  PDF that shows the same problem is more useful than the original anyway.

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

The hook is bypassable with `--no-verify`, deliberately: it is a convenience,
not a gate.

## Releasing

```bash
uv run cz bump
git push --follow-tags
```

`cz bump` reads the commits since the last tag, works out the version bump,
updates `pyproject.toml`, writes `CHANGELOG.md` and tags.

The project is pre-1.0, so `major_version_zero` is set: a breaking change bumps
the minor rather than jumping to 1.0. Drop that once the imposition parameters
and preset format are stable. Commits before `580efa6` predate this convention
and are excluded from the changelog.

## What is worth working on

[README's Known gaps](README.md#known-gaps) is the honest list. The largest is
that **Windows and macOS builds have never been run** — the PyInstaller spec is
written to be correct there but is unverified. CI on hosted runners is the
intended fix, and would unblock most of the rest.

## Licensing

Bookwork is GPL v3-or-later. Contributions are accepted under the same terms.
New source files need the licence header the existing ones carry — copy it from
any file in `src/`.

Note that PyMuPDF, which every build depends on, is AGPL v3; see
[docs/third-party.md](docs/third-party.md) before adding dependencies, since
licence compatibility is not automatic in a GPL project.

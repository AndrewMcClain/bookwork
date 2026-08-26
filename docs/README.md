# Bookwork docs

| Document | What is in it |
|---|---|
| [design.md](design.md) | How the app is put together: stack, module map, the imposition pipeline, parameters, how it is tested. Start here. |
| [decisions.md](decisions.md) | Choices that are not obvious from the code, and the failures that motivated them. Check here before changing something that looks odd. |
| [background.md](background.md) | The manual PostScript workflow Bookwork replaces, and where each of its rough edges went. Explains why the project exists. |

## Adding to these

`decisions.md` is the one that earns its keep. When you make a call that a
future reader would otherwise have to rediscover — especially one motivated by
a bug that was hard to find — add an entry saying what was decided, why, and
what broke. Several entries there exist because the knowledge was only in a
commit message and nearly got lost.

Design documents that go stale are worse than none, because they are believed.
If you change behaviour that `design.md` describes, change the description in
the same commit.

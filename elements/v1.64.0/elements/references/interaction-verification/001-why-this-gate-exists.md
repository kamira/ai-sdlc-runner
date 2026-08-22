## Why this gate exists

A one-off script that is wrong gets rewritten; the cost stops there. A **reused** artefact is
different: every reuse amplifies the same unverified assumption. And the failures tend not to be
in the logic — they are on the **usage surface**: the button that does nothing, the tab order
that skips a field, the CLI that returns 0 with a required argument missing, the library that
raises an undocumented exception on bad input.

Unit tests do not reach there, and an agent writing its own tests reaches there least of all: it
covers the call paths it thought of, and usage-surface bugs are precisely the ones where *the
user does this, and the author never considered it*.


# The seats' own words

Round 2 said the same thing from both seats: the only surviving witness to what a seat found was
the corrected author's summary of it, and this repository's entire recorded history is disagreement
being flattened. So the verdicts live here, whole, and the change record's summary is a reading of
these files rather than a replacement for them.

| File | Verdict |
|---|---|
| `round-1-codex-seat.md` | `DESIGN: not sound` |
| `round-1-fable-seat.md` | `DESIGN: sound with changes` |
| `round-2-codex-seat.md` | `ROUND 2: fail` |
| `round-2-fable-seat.md` | `ROUND 2: pass with changes` |
| `round-3-codex-seat.md` | `ROUND 3: fail` · `NEXT: build task 12` |
| `round-3-fable-seat.md` | `ROUND 3: fail` · `NEXT: build task 12` |
| `readme-codex-seat.md` | `README: not sound` |
| `readme-fable-seat.md` | `README: sound with changes` |

All three rounds split on the verdict, so none of them passed — a tie does not pass, and that rule
applies to this repository's own design record or it is not a rule.

**Round 3 is where they agreed on something.** Both seats independently answered `NEXT: build task
12`, having found that round 3 turned up four defects *created by round 2's corrections* and zero new
design findings. Round 1's defects were about the design, round 2's about the corrections, round 3's
about the corrections to the corrections. Task 12 is built.

## Provenance, stated exactly

The two codex files are cut from the seat's raw stdout, unedited.

The three codex files are cut from the seat's raw stdout, unedited.

`round-3-fable-seat.md` is extracted from the seat's own transcript, unedited.

`round-1-fable-seat.md` and `round-2-fable-seat.md` are the text the seat returned, **transcribed**:
their raw transcripts are zero bytes on disk — the harness did not retain them — so unlike the other
four these cannot be re-derived from an artefact I did not write. That is a weaker chain of custody
and it is stated here rather than left for a later round to discover. If it matters for a decision,
treat the other four as the stronger evidence.

## Reading them against the record

The record's *Review round 1* section separates what both seats found from what one seat found.
Round 2 marked that separation **not substantiated** — correctly, at the time, because these files
did not exist. It is checkable now. If the record's summary and one of these files disagree, the
file is right.

One correction round 2 forced, worth naming here because it is a methodological error rather than a
factual one: the round-1 brief *handed both seats* the suspend/resume alternative as its worked
example, and the record then reported their agreement as independent convergence. It was evidence
of the primer. `review-round-1-brief.md`, question Q2, is where to check that.

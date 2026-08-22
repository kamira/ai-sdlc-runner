## Decision: risk × gate

Look up `auto` or `halt` by the change's **Risk** (from the CHG/ACC risk field):

| gate \ Risk | low | medium | high |
|-------------|-----|--------|------|
| requirement_confirmed | auto | auto | **halt** |
| structure_confirmed | auto | auto | **halt** |
| before_implement | auto | auto | **halt** |
| acceptance_failed | auto | **halt** | **halt** |
| before_merge_or_release | auto | **halt** | **halt** |

Intuition: **low risk runs fully autonomously; medium halts at "merge/deliver" and "acceptance failed"; high halts at every gate.**


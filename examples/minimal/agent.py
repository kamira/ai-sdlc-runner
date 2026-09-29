#!/usr/bin/env python3
"""The smallest agent this runner will accept.

One process per ask. The work order arrives as JSON on **stdin**; the answer goes to **stdout** as
JSON. That is the whole contract — nothing else is read, and a non-zero exit is a failed attempt.

What each ask must answer travels in the order itself, under `reply`: the keys the run acts on and
what each accepts, for the way that ask was dispatched, as JSON Schema under `reply.schema`. For
this example — one model per node, and `next_module` decided by "frontier" — it says:

  a decision node    {"verdict": "<branch>"}   one of the branches the node offers
  pm_plan            {"modules": [...]}        required when next_module is "frontier"
  engineer_build     {"module": "<id>"}        which module this build produced
                     {"module": ""}            nothing left to build; ends the module loop.
                                               Omitting the key entirely is NOT this -- it means
                                               the question was not answered, and the loop stays
                                               open (CHG-20260823-50)
  a seat on a panel  {"verdict": "pass"|"fail", "why": "..."}
  a seat at intake   {"missing": [...], "problems": [...], "unsafe": [...]}
  anything else      {} or {"why": "..."}; nothing in it is acted on

A decision node asked of a panel of models reads "pass" / "fail" / "undecided" instead of its
branch names, and an engineer that could not build answers {"module": "", "error": "..."}; the
order's `reply` says which applies. Any answer may add "why"; no other key belongs in it.

Run it:  runner --config examples/minimal/runner.yaml run --plan examples/minimal/plan.json --risk low
"""
import json
import pathlib
import sys

MODULES = ["greet"]
order = json.loads(sys.stdin.read())
node, seat = order["node_id"], order.get("seat")


def say(payload):
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(0)


if seat:
    if node == "intake_review":
        # A survey, not a vote: what is missing and what is wrong. This one finds nothing, so the
        # run proceeds — answer with real aspect ids from `intake.ASPECT_IDS` to see it stop.
        say({"missing": [], "problems": [], "unsafe": []})
    say({"verdict": "pass", "why": f"{seat}: nothing found"})

if node == "pm_plan":
    say({"modules": MODULES, "why": "one module"})

if node == "engineer_build":
    pathlib.Path("greet.py").write_text(
        'def greet(name: str) -> str:\n    return f"hello, {name}"\n', encoding="utf-8")
    say({"module": MODULES[0], "why": "wrote greet.py"})

branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
          "re_review": "pass", "qa_accept": "pass"}.get(node)
say({"verdict": branch} if branch else {"why": f"{node} done"})

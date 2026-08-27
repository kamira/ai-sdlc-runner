"""cli.py — the runner's command line.

CHG-20260823-01. What is left after the skill dependency went is small on purpose: this runner drives
one flow, and the flow is `graph.py`. The subcommands that existed to manage a vendored skill —
`migrate`, `check`, the store resolution, the multi-project workspace and its structure scan — went
with the thing they managed. Nothing here resolves a skill path, because there is no skill.

## Dispatch: one process per ask

A command backend gets **one process per ask**. That is the session boundary made physical: there is
no handle to keep alive, so "closed after the ask" is not a promise a backend has to keep. The work
order goes in as JSON on stdin and nothing else does — no tool list, no role prompt, nothing a
harness owns.

`--seat-model` routes a named seat to a different command, which is what makes cross-model review
real: **the same question, different answerers.** The routing lives here and never in the order.
"""
from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import attachments as attach_mod
from . import conversations as conv_mod
from . import paths
from . import plan as plan_mod
from . import store as store_mod
from . import engine, models as models_mod, graph, policy, settings as settings_mod, ship, tui, workorder

DEFAULT_CONFIG = "config/runner.yaml"


def load_config(path: str) -> dict:
    """Read runner.yaml. PyYAML if present, else a small reader for the flat keys we use.

    The fallback has to understand an **inline list**, because `agent_command` is documented as one
    and PyYAML is optional — a reader that silently split ``["python", "agent.py"]`` on whitespace
    produced an argv whose first element was ``'["python",'``, which failed only on machines without
    PyYAML. That is every CI runner here, and none of the developer machines.
    """
    p = Path(path)
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8")
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        config: Dict[str, object] = {}
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line or line.startswith("-"):
                continue
            key, _, raw = line.partition(":")
            raw = raw.strip()
            if not raw:
                continue
            if raw.startswith("["):
                try:
                    config[key.strip()] = json.loads(raw)
                    continue
                except json.JSONDecodeError:
                    pass
            config[key.strip()] = raw.strip('"').strip("'")
        return config


# --------------------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------------------

class _Stub(engine.Session):
    """Answers nothing, records that it was asked. The default, so a dry run costs nothing."""

    def describe(self) -> str:
        return "stub"

    def ask(self, order):
        return {"backend": "stub", "node_id": order["node_id"], "role": order["role"]}

    def close(self):
        pass


class CliError(Exception):
    """Raised when a backend cannot be made to produce an answer."""


class _Process(engine.Session):
    """One process per ask: the work order on stdin, the JSON it prints back as the answer.

    The reply is **parsed**, not just captured. The engine routes on what a review or a confirmation
    actually said, so an answer left as a blob of stdout is an answer that decides nothing — the
    first version of this class returned exactly that, which made every real agent's verdict
    unroutable while the stub-backed tests stayed green.

    The agent's own keys win over the process metadata kept alongside them, so an agent that answers
    ``{"verdict": "fail"}`` fails the node no matter what the exit code says.
    """

    def __init__(self, argv: List[str], timeout: int, retries: int = 0):
        self.argv, self.timeout, self.retries = argv, timeout, retries
        #: Every attempt that failed, so a run that took four tries does not read like one that
        #: took one. An unrecorded retry turns a flaky backend into a mystery.
        self.attempts: List[str] = []

    def describe(self) -> str:
        """Which backend this is, for the panel-diversity note. The command, not the process."""
        return " ".join(self.argv)

    def ask(self, order):
        # Task 7. Retries live HERE, in the dispatcher, and never in the engine. Putting them in the
        # engine would make "one ask, one session" untrue: the engine would be opening a second
        # session for a question it had already asked, and the property that makes a panel a panel
        # is exactly that each voice got its own.
        #
        # A retry is for a backend that FAILED TO ANSWER -- crashed, timed out, wrote nothing a
        # reader could parse. It is never for an answer somebody dislikes: retrying a `fail` until
        # it comes back `pass` is not a retry, it is shopping for a verdict, and the whole point of
        # the panel is that nobody gets to do that. So the retry loop sits above the parse and below
        # the routing, and never sees the verdict at all.
        attempt, last = 0, None
        while True:
            attempt += 1
            try:
                proc = subprocess.run(self.argv, input=workorder.to_json(order),
                                      capture_output=True, text=True, timeout=self.timeout)
                if proc.returncode != 0:
                    raise CliError(
                        f"{self.argv[0]!r} exited {proc.returncode} answering "
                        f"{order['node_id']!r}: {proc.stderr.strip() or 'no stderr'}")
                break
            except (CliError, subprocess.TimeoutExpired) as exc:
                last = exc
                if attempt > self.retries:
                    # Out of attempts. The question stays pending in the journal, exactly as it
                    # would have without retries -- retrying changes how many times we tried, not
                    # what happens when trying stops working.
                    raise CliError(
                        f"{self.argv[0]!r} failed {attempt} time(s) answering "
                        f"{order['node_id']!r}; giving up. Last failure: {exc}")
                self.attempts.append(
                    f"{order['node_id']}: attempt {attempt} failed ({type(exc).__name__}), "
                    f"retrying")
        del last
        answer = {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return answer
        if isinstance(parsed, dict):
            answer.update(parsed)
        return answer

    def close(self):
        pass


def session_factory(config: dict, seat_models: Optional[Dict[str, List[str]]] = None,
                    registry: Optional["models_mod.Registry"] = None):
    """Build the factory the engine opens a session from, routing by seat or by model.

    Three ways to name a backend, and they are tried most-specific first: the **model** a node's mode
    picked, then the **seat**, then the default. Routing lives here and never in the work order —
    which is what makes a panel meaningful, because the order every voice receives is identical and
    only the answerer differs.

    A model id the registry does not have is an **error**. Falling back to the default would mean a
    panel of three quietly answered three times by one backend, which is the shape of failure this
    whole change exists to make impossible.
    """
    seat_models = seat_models or {}
    default = config.get("agent_command")
    timeout = int(config.get("agent_timeout", 600))
    retries = int(config.get("agent_retries", 0))

    def factory(seat: Optional[str] = None, model: Optional[str] = None):
        argv = None
        # A seat may name a registry model, exactly as a node does. Resolved first, because a plain
        # string that happens to be a model id meaning "run this program called claude" would be a
        # nasty way to find out the two naming schemes had diverged.
        if model is None and seat is not None and registry is not None:
            named = seat_models.get(seat)
            if isinstance(named, str):
                try:
                    registry.get(named)
                    model = named
                except models_mod.ModelError:
                    pass            # not a model id; treated as argv below, as it always was
        if model and registry is not None:
            entry = registry.get(model)          # raises if it is not a model this project has
            if entry.transport != models_mod.CLI:
                raise CliError(
                    f"model {model!r} is {entry.transport!r}, and this runner dispatches by running "
                    f"a command. An api model needs a backend that speaks to it — there is none "
                    f"yet, and pretending otherwise would send the work to the default and report "
                    f"it as {model!r}.")
            argv = list(entry.command)
        if argv is None:
            argv = seat_models.get(seat) or default
        if not argv:
            return _Stub()
        return _Process(list(argv) if isinstance(argv, list) else str(argv).split(),
                        timeout, retries)

    return factory


# --------------------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------------------

def cmd_flow(args: argparse.Namespace) -> int:
    """Print the flow this runner drives — the fastest way to see what it will actually do."""
    graph.validate()
    for node in graph.NODES:
        who = f"[{node.role}]" if node.role else "[runner]"
        gate = f"  gate:{node.gate}" if node.gate else ""
        print(f"{node.id:22s} {who:11s} {node.label}{gate}")
        for label, target in sorted(node.branches.items()):
            print(f"{'':22s} {'':11s}   {label} → {target}")
    print(f"\n{len(graph.NODES)} nodes, {len(graph.asking_nodes())} of them ask someone; "
          f"{len(set(graph.gates_used()))} gates; "
          f"roles: {', '.join(graph.roles_used())}")
    return 0


def cmd_policy(args: argparse.Namespace) -> int:
    """Print the governance: roles, gates, seats. Ours, not read from anywhere."""
    print("roles")
    for role in policy.ROLES:
        caps = "".join(c for c, on in
                       (("s", role.can_spawn), ("w", role.can_write), ("x", role.can_execute)) if on)
        print(f"  {role.name:10s} {caps:3s} {role.label}")
    print("\ngates (risk → verdict)")
    for gate, grades in policy.GATES.items():
        print(f"  {gate:22s} " + "  ".join(f"{r}:{grades[r]}" for r in policy.RISKS))
    print(f"\nseats (floor {policy.SEAT_FLOOR})")
    for seat in policy.SEATS:
        print(f"  {seat.name:12s} {'veto' if seat.veto else '    '}  {seat.label}")
    return 0


def cmd_settings(args: argparse.Namespace) -> int:
    """Show the settings, or open the screen that edits them.

    The requirement asks for the seat count and the high-risk bypass to be *set in the GUI*, and
    prints them here as well because a bypass has to be visible to somebody who never opens a menu
    — in CI, in a log, in a review of what this project is configured to do.
    """
    try:
        current = settings_mod.load(args.settings)
    except settings_mod.SettingsError as exc:
        print(f"error: {exc}")
        return 2

    if args.show:
        print(current.describe())
        if current.below_floor():
            print(f"warning:       running below the review floor of {policy.SEAT_FLOOR}. "
                  f"Every run records that it did.")
        return 0

    chosen = settings_mod.edit(current)
    if chosen is None:
        print("unchanged")
        return 0
    settings_mod.save(chosen, args.settings)
    print(f"saved {args.settings}: {chosen.describe()}")
    return 0


def effects_provider(plan: dict):
    """The effects each node carries out, from the plan's ``ship`` block — or ``None``.

    Two nodes have one. `pr`: record the intent, branch, commit, push, open the PR. `record_module`,
    when the plan names a ``task``: tick it, and write the acceptance record if the plan names one.
    Both are built by `ship`, so the ordering and the probes live in one place rather than being
    restated here. With no ``ship`` block the flow runs without side effects, which is what a dry
    run wants.
    """
    settings = plan.get("ship")
    if not settings:
        return None

    repo = settings["repo"]
    chg_id = settings["chg_id"]
    body = settings.get("chg_body")

    def _write_chg() -> None:
        if body is None:
            raise ship.ShipError(
                f"the plan ships {chg_id} but supplies no chg_body — the intent has to be written "
                f"down before anything else happens, and this runner will not invent it")
        path = Path(repo) / "docs" / "changes" / f"{chg_id}.md"
        paths.makedirs(path.parent)
        paths.write_text(path, body)

    sequence = ship.effects_for(
        repo=repo, chg_id=chg_id, branch=settings["branch"], message=settings["message"],
        write_chg=_write_chg, remote=settings.get("remote", "origin"))

    task = settings.get("task")
    acc_id = settings.get("acc_id")
    acc_body = settings.get("acc_body")

    def _tick() -> None:
        raise ship.ShipError(
            f"ticking task {task!r} of {chg_id} is the lead's judgement written into the ledger, "
            f"not something this runner writes on its behalf. Tick it, then re-run — the probe "
            f"reads the file, so a resumed run will find it done.")

    def _write_acc() -> None:
        if acc_body is None:
            raise ship.ShipError(
                f"the plan records acceptance as {acc_id} but supplies no acc_body — an acceptance "
                f"record with no evidence is the false green this repo keeps catching")
        path = Path(repo) / "docs" / "acceptance" / f"{acc_id}.md"
        paths.makedirs(path.parent)
        paths.write_text(path, acc_body)

    record = ship.record_effects(repo, chg_id, task, acc_id, tick=_tick,
                                 write_acc=_write_acc) if task else []

    def provider(node_id: str):
        if node_id == "pr":
            return sequence
        if node_id == "record_module":
            return record
        return ()

    return provider


def _report_pending(journal) -> None:
    """Say what is still waiting to be asked, if anything.

    `AskJournal.pending()` is the point of journalling before the ask — and until this printed it,
    nothing outside the tests ever read it, which a verifier called out. A question preserved where
    nobody looks is preserved in the same sense as a backup nobody restores.
    """
    if journal is None:
        return
    for entry in journal.pending():
        print(f"still to ask:  {entry['node_id']} ({entry['ask_id']}) — "
              f"{entry['order'].get('role_label', entry['order'].get('role'))}")


def _read_store(args: argparse.Namespace):
    try:
        return conv_mod.backend(args.store, root=args.store_root)
    except conv_mod.ConversationError as exc:
        print(f"error: {exc}")
        raise SystemExit(2)


def cmd_conversations(args: argparse.Namespace) -> int:
    """List what has been stored, by project — or bring an older store across."""
    back = _read_store(args)
    if getattr(args, "import_from", None):
        return _import(args, back)
    pid = conv_mod.project_id(args.project) if args.project else None
    projects = {p["id"]: p.get("name", "?") for p in back.projects()}
    heads = back.conversations(pid)
    if not heads:
        print("no conversations stored" + (f" for project {args.project!r}" if args.project else ""))
        return 0
    for head in heads:
        proj = head.get("project") or {}
        name = proj.get("name") or projects.get(proj.get("id"), "?")
        print(f"{head.get('conversation_id')}  {name}")
    return 0


def _printable(value: object) -> str:
    """A string safe to send to a terminal, whatever it came from.

    Conversation ids and refusal reasons are taken from files this runner did not write. A legacy
    store holding a conversation whose id is `evil\x1b]0;pwned\x07` retitles the operator's terminal
    window when the import names it, and `\x1b[31m` recolours everything printed after. The escapes
    reached the terminal intact — verified by running it. Every C0 and C1 control character is shown
    as its escape instead; nothing else is altered, so CJK ids print as themselves.
    """
    return "".join(c if (c.isprintable() or c == " ") else
                   ("\\x%02x" % ord(c) if ord(c) < 0x100 else "\\u%04x" % ord(c))
                   for c in str(value))


def _import(args: argparse.Namespace, back) -> int:
    """Copy a JSONL store into this one, once, and leave the files where they are.

    Nothing is deleted. A migration that removes its own source has no way back if it was wrong, and
    this one is reversible for exactly as long as the directory is still there.
    """
    try:
        report = conv_mod.import_file_store(args.import_from, back)
    except conv_mod.ConversationError as exc:
        print(f"error: {exc}")
        return 2
    imported, skipped, refused = report["imported"], report["skipped"], report["refused"]
    print(f"imported {len(imported)} conversation(s), {report['turns']} turns, "
          f"from {args.import_from}")
    for cid in imported:
        print(f"  + {_printable(cid)}")
    if skipped:
        # Skipped rather than merged: a turn whose `seq` matches and whose body differs has no
        # answer that is not a guess.
        print(f"skipped {len(skipped)} already here, whole:")
        for cid in skipped:
            print(f"  = {_printable(cid)}")
    if refused:
        # The bucket the first version did not have. A conversation the importer will not touch is
        # the thing an operator most needs to be told about, and it used to arrive as a traceback
        # after a partial write.
        print(f"\nREFUSED {len(refused)}, left on disk:")
        for entry in refused:
            print(f"  ! {_printable(entry['conversation_id'])}: "
                  f"{_printable(entry['why'])}")
    print(f"\n{args.import_from} is untouched. Check the import, then remove it yourself.")
    return 2 if refused else 0


def cmd_export(args: argparse.Namespace) -> int:
    """Write one conversation out in the format the operator chose.

    The format is asked for rather than defaulted, because the three are not interchangeable: only
    `json` is lossless, and a silent default would pick which information the operator loses.
    """
    back = _read_store(args)
    # `--store-remote allow` recorded a relaxation here, because `export` runs outside any walk and
    # `RunReport.relaxations` does not exist at the moment it would be used. Both are gone with the
    # remote backend (CHG-20260823-35): there is no store that can be off this machine, so there is
    # no locality to relax and nothing truthful to record.
    if not args.project or not args.conversation:
        print("error: export needs --project NAME and --conversation ID. "
              "`runner conversations --project NAME` lists them.")
        return 2
    try:
        document = back.read(conv_mod.project_id(args.project), args.conversation)
        text = conv_mod.export_conversation(document, args.format)
    except conv_mod.ConversationError as exc:
        print(f"error: {exc}")
        return 2
    if args.out:
        # `Path.write_text` grew a `newline=` keyword in 3.10 and this project's floor is 3.9, so
        # the newline is pinned here instead — a CSV whose line endings depend on the OS is a
        # different file on each half of the CI matrix.
        # Through `paths`, which pins the newline for the same reason. `--out` is an operator-chosen
        # path and was one of five writes bypassing the module CHG-20260823-32 claimed every write
        # went through.
        paths.write_text(args.out, text)
        print(f"wrote {args.out} ({len(document.get('turns') or [])} turns, {args.format})")
        if args.format == "csv":
            print("note: csv is the lossy form — nested values are JSON text in the *_json "
                  "columns, cells are defused against spreadsheet formula execution, and "
                  "over_spreadsheet_cell_limit flags rows a spreadsheet will truncate.")
    else:
        sys.stdout.write(text)
    return 0


def _store_flags(parser: argparse.ArgumentParser) -> None:
    """The conversation-store flags, on every command that stores one.

    `--project` has **no default**. Both review seats refused the first design's default — the plan
    file's parent directory — because that files every `examples/plan.json` run under a project
    called "examples", and `serve` may have no plan at all. A location is not an identity, and there
    is no other fact available to default from, so it is asked for.
    """
    parser.add_argument("--project", default=None, metavar="NAME",
                        help="what this conversation is filed under. Required to store one; there "
                             "is no default, because a directory name is a location rather than a "
                             "project. The name is stored as data — a hash of it is what touches "
                             "the filesystem.")
    # Kept as a choice of one. `mongo` and `tinydb` are refused **by name**, saying they were
    # removed and when — `unknown store 'mongo'` reads as a typo to someone whose config worked
    # last week.
    parser.add_argument("--store", choices=conv_mod.BACKENDS, default="sqlite",
                        help="which conversation store. `sqlite` is the store (CHG-20260823-41); "
                             "`file` is the JSONL layout that came before it, kept so an existing "
                             "one can be read and imported. `mongo` and `tinydb` were removed in "
                             "CHG-20260823-35 and are refused by name.")
    parser.add_argument("--store-root", default=None, metavar="DIR",
                        help="where the store lives (default .runner/conversations). For `sqlite` "
                             f"the database is <DIR>/{conv_mod.DB_NAME}.")


def _open_conversation(args: argparse.Namespace, journal_dir=None, run=None):
    """Open the conversation for this invocation, or return ``None`` if none was asked for.

    Refusals here are fatal and print: a store the operator asked for and did not get is not a
    detail to discover later. Write failures, once open, are the opposite — see
    `Conversation.write_errors`.
    """
    if not getattr(args, "project", None):
        return None
    try:
        back = conv_mod.backend(args.store, root=args.store_root)
        conv = conv_mod.Conversation.resume_or_open(back, args.project, journal_dir, run=run)
    except conv_mod.ConversationError as exc:
        print(f"error: {exc}")
        raise SystemExit(2)
    return conv


def cmd_run(args: argparse.Namespace) -> int:
    """Walk the flow for one change."""
    config = load_config(args.config)
    if not args.plan:
        print("error: run needs --plan <file>: the objective, instructions, done-criteria and "
              "branch choices for this change. The governance is ours; the work is not.")
        return 2
    try:
        # Closed. Unknown keys are refused rather than ignored — the plan was the outermost schema
        # and the only one with no validation at all, and the case that decided it is `ship`: a
        # misspelt one made a run perform no side effects and report `finished`.
        plan = plan_mod.load(args.plan)
    except plan_mod.PlanError as exc:
        print(f"error: {exc}")
        return 2

    journal = engine.AskJournal(args.ask_journal) if args.ask_journal else None

    # The assignment store, read the same way `serve` reads it: the plan wins where it speaks, the
    # store fills where it is silent. `--assignment-store none` opts out for a run that must depend
    # on the plan alone.
    plan_assignments = {"node_models": plan.get("node_models") or {},
                        "seat_models": plan.get("seat_models") or {}}
    resolved_assignments = dict(plan_assignments)
    assignment_source: Dict[str, str] = {}
    config_registry: Optional[models_mod.Registry] = None
    store_path = args.assignment_store or ".runner/config.sqlite"
    if str(store_path).lower() != "none":
        try:
            config_db = store_mod.connect(store_path)
            resolved_assignments, assignment_source = store_mod.resolve(
                plan_assignments,
                {"node_models": store_mod.node_models(config_db),
                 "seat_models": store_mod.seat_models(config_db)})
            # The registry travels with the assignment or the assignment cannot be dispatched.
            config_registry = store_mod.load_registry(config_db) or None
        except store_mod.StoreError as exc:
            print(f"error: {exc}")
            return 2
        except models_mod.ModelError as exc:
            print(f"error: the assignment store holds a model this runner refuses: {exc}")
            return 2
    try:
        saved = settings_mod.load(args.settings)
    except settings_mod.SettingsError as exc:
        print(f"error: {exc}")
        return 2

    # A flag beats the file. Someone typing `--seats 1` right now is making a decision about this
    # run; the file is the standing one. Neither is silent: whichever produces a floor crossing, the
    # run records it.
    seats = args.review_seats if args.review_seats is not None else saved.review_seats
    # `--no-high-risk-mode` turns a saved bypass off for this run. Without it the file and the flag
    # were OR-ed, so a bypass persisted in settings could not be declined for a single run — a
    # verifier pointed out that "a flag beats the file" held only in the relaxing direction, which
    # is the wrong one to be asymmetric in.
    if args.no_high_risk_mode:
        # Declining the bypass means "run at the floor", not "ask me about it again". Leaving a
        # below-floor seat count in place sent the operator straight into the confirmation prompt
        # they had just declined on the command line — a flag that reopens the question it answers.
        high_risk = False
        if seats is not None and seats < policy.SEAT_FLOOR:
            print(f"note:          --no-high-risk-mode: {seats} seat(s) is below the floor, "
                  f"opening {policy.SEAT_FLOOR}")
            seats = None
    else:
        high_risk = bool(args.high_risk_mode) or saved.high_risk_mode
    if seats is not None and seats < policy.SEAT_FLOOR and not high_risk:
        high_risk = tui.confirm_high_risk(seats, policy.SEAT_FLOOR)
        if not high_risk:
            seats = None

    conversation = _open_conversation(
        args, journal_dir=args.ask_journal,
        run={"journal": str(Path(args.ask_journal).resolve()) if args.ask_journal else None,
             "plan": str(args.plan)})
    cfg = engine.RunConfig(
        conversation=conversation,
        node_specs=plan.get("node_specs", {}),
        decisions=plan.get("decisions", {}),
        risk=args.risk or plan.get("risk", "high"),
        autonomy=plan.get("autonomy"),
        review_seats=seats,
        high_risk_mode=high_risk,
        operations=plan.get("operations", {}),
        confirmed=tuple(args.confirm or ()),
        rulings=tuple(_rulings(args.rule or ())),
        # The same resolution `serve` uses. Without this `runner run` ignored the store
        # entirely — an assignment made in the console governed nothing on the command line, and
        # "the project's standing assignment" was a phrase about a table two commands disagreed on.
        node_models=resolved_assignments.get("node_models") or {},
        effects=effects_provider(plan),
        ordinary_commands=saved.ordinary_commands,
        undeclared=args.undeclared,
        resume=bool(args.resume),
        journal=journal,
    )
    seat_models = dict(resolved_assignments.get("seat_models") or {})
    for pair in args.seat_model or ():
        seat, _, command = pair.partition("=")
        if not command:
            print(f"error: --seat-model wants SEAT=COMMAND, got {pair!r}")
            return 2
        if seat not in policy.BY_SEAT:
            print(f"error: no seat {seat!r}; this runner defines {sorted(policy.BY_SEAT)}")
            return 2
        seat_models[seat] = command.split()
    try:
        # **With the registry.** Without it `session_factory` cannot turn a stored model id into
        # a command — `registry is not None` guards that whole branch — so `run` selected a model
        # from the store and silently dispatched to the default backend instead.
        #
        # The same class as round 1's critical finding, one command over: configuration that looks
        # connected and does not govern execution. Found by a seat reading the call, not the store.
        report = engine.walk(
            cfg, session_factory(config, seat_models, registry=config_registry), enabled=True)
    except (engine.EngineError, policy.PolicyError, CliError) as exc:
        print(f"halted: {exc}")
        _report_pending(journal)
        return 10

    _report_pending(journal)

    for relaxation in report.relaxations:
        print(f"relaxation:    {relaxation}")
    for line in report.on_trust:
        print(f"unverified:    {line}")
    for line in report.confirmations:
        print(f"confirmed:     {line}")
    for line in report.single_model_panels:
        print(f"single model:  {line}")
    for decision in report.adjudications:
        seat_line = ", ".join(f"{k}={v}" for k, v in sorted(decision["verdicts"].items()))
        print(f"panel:         {decision['node_id']} → {decision['outcome']} ({seat_line})")
    if report.resumed:
        print(f"resumed:       {len(report.resumed)} ask(s) answered from the journal, "
              f"not re-asked")
    for node_id, outcome in report.effects.items():
        print(f"effects:       {node_id} applied={outcome['applied']} "
              f"already_met={outcome['already_met']}")
    filled = sorted(k for k, v in assignment_source.items() if v == store_mod.FROM_STORE)
    if filled:
        # `serve` prints its override count and `run` printed nothing, so "neither source is
        # silent" held on one of the two commands. A seat noticed the asymmetry.
        print(f"from the store: {len(filled)} assignment(s) the plan did not name — "
              f"{', '.join(filled[:4])}{' …' if len(filled) > 4 else ''}")
    print(f"visited:       {len(report.visited)} node(s)")
    print(f"asks:          {len(report.asks)}")
    print(f"stopped at:    {report.halted_at} — {report.halt_reason}")

    # Say which kind of stop this was. The report has been able to distinguish them since task 1;
    # printing the distinction is what makes it usable from here, and leaving it out would be a
    # field the operator cannot see -- decorative data with an audience.
    for failure in report.store_errors:
        # The summary channel. `_guarded` already spoke at the moment of failure, which is the one
        # that survives a crash; this is the one an operator reading the end of a run cannot miss.
        # A seat found the first version writing neither.
        print(f"store failed:  {failure}", file=sys.stderr)
    print(f"state:         {report.state}")
    if report.state == engine.SUSPENDED and report.suspended:
        stop = report.suspended
        if stop.get("undecided"):
            # A tie and a gate are different questions, so they get different sentences. Offering
            # "--confirm" here would be offering a control that cannot answer what is being asked.
            print(f"waiting for:   somebody to break a tie at {stop['node_id']}")
            print(f"               {stop.get('reason', 'the panel was split')}")
            for voice, verdict in sorted((stop.get("verdicts") or {}).items()):
                print(f"               {voice}: {verdict}")
            print(f"continue with: --resume --rule {stop['node_id']}="
                  f"{'|'.join(stop.get('branches') or [])}")
        else:
            print(f"waiting for:   a decision on {stop['gate']} at {stop['node_id']}")
            print(f"continue with: --resume --confirm {stop['gate']}"
                  + (f"  (run {stop['run_id']})" if stop.get("run_id") else ""))
    for line in report.dispatches:
        print(f"dispatched:    {line}")
    for line in report.rulings:
        print(f"ruled:         {line}")
    return 0


def _rulings(raw):
    """Parse ``NODE=BRANCH`` arguments, refusing anything malformed.

    Guessing here would be the worst option: a mistyped ruling that silently becomes a different
    branch is a person's decision being changed without them knowing, at the one place in the flow
    where the whole point is that a person decided.
    """
    out = []
    for item in raw:
        node_id, sep, branch = item.partition("=")
        if not sep or not node_id or not branch:
            raise SystemExit(
                f"--rule expects NODE=BRANCH; got {item!r}. Say which node's tie you are breaking "
                f"and which way.")
        out.append(engine.Ruling(node_id=node_id, branch=branch))
    return out


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the console's back end. **Local only** — see `server.py` for why that is three rules.

    The token is printed once, here, on the operator's own terminal. Printing it is the point: what
    makes "whoever holds it is the operator" a true statement is that it reaches somebody who can
    read this machine's filesystem, and nobody else.
    """
    from . import server

    if not args.plan:
        print("error: serve needs --plan <file>, the same one `run` takes. A console with no plan "
              "behind it would accept an instruction and quietly answer nothing.")
        return 2
    try:
        # Closed. Unknown keys are refused rather than ignored — the plan was the outermost schema
        # and the only one with no validation at all, and the case that decided it is `ship`: a
        # misspelt one made a run perform no side effects and report `finished`.
        plan = plan_mod.load(args.plan)
    except plan_mod.PlanError as exc:
        print(f"error: {exc}")
        return 2
    try:
        saved = settings_mod.load(args.settings)
    except settings_mod.SettingsError as exc:
        print(f"error: {exc}")
        return 2

    # A journal is NOT optional here, and defaulting it is not a convenience -- it is the thing that
    # makes a suspended run resumable at all.
    #
    # Found by running a three-module project through the console: every gate approval re-walked the
    # flow from `intake`, because without a journal `resume` is False and nothing is skipped. The
    # demo's agent happened to be idempotent, so the only trace was a review seeing modules that had
    # not been built yet at the point it was asked. A real agent would have rebuilt every module and
    # re-opened every PR, once per gate.
    #
    # It is also task 1's second answer arriving as a constraint: the run id IS the journal, so a
    # server without one cannot validate the `run_id` on a targeted approval — the staleness check
    # is simply dead. The engine already refuses `resume=True` with no journal; `serve` was the one
    # caller that could walk around that by never asking for it.
    journal = engine.AskJournal(args.ask_journal or (Path(args.token_dir) / "asks"))

    store = attach_mod.Store(args.attachments or (Path(args.token_dir) / "attachments"))
    conversation = _open_conversation(args, journal_dir=journal.dir,
                                      run={"journal": str(journal.dir.resolve()),
                                           "plan": str(args.plan or "")})

    def make_config(instructions, approvals, rulings, artifacts=(), rejections=(),
                    intake_history=()):
        return engine.RunConfig(
            conversation=conversation,
            node_specs=plan.get("node_specs", {}),
            decisions=plan.get("decisions", {}),
            risk=args.risk or plan.get("risk", "high"),
            autonomy=plan.get("autonomy"),
            review_seats=saved.review_seats,
            high_risk_mode=saved.high_risk_mode,
            operations=plan.get("operations", {}),
            confirmed=approvals,
            rulings=rulings,
            # **The current** assignment, not the plan's — resolved on every walk.
            #
            # This read `plan.get("node_models")`, so an assignment edited through the console
            # changed the display and not the run: `_reassign` refreshed `held`, and the engine
            # went on receiving whatever the plan said at startup. A seat found it, and the comment
            # on `_reassign` claimed the opposite in as many words -- "a console showing a stale
            # merge would be reporting an assignment that is not the one the next run will use".
            #
            # Resolved per walk rather than captured once, because a value captured at startup is
            # how the defect happened.
            node_models=current_assignments().get("node_models") or {},
            artifacts=artifacts,
            instructions=instructions,
            rejections=rejections,
            intake_history=intake_history,
            effects=effects_provider(plan),
            ordinary_commands=saved.ordinary_commands,
            undeclared=args.undeclared,
            resume=True,
            journal=journal,
        )

    # The same factory `run` uses, so the console dispatches exactly the way the command line does.
    # A console that answered through a different path would be a second runner wearing the first
    # one's governance.
    registry_path = Path(args.models or (Path(args.token_dir) / "models.json"))
    try:
        registry = models_mod.load(registry_path)
    except models_mod.ModelError as exc:
        print(f"error: {exc}")
        return 2

    # The assignment store. This is where 「model 模型配置」 actually persists -- both halves of it,
    # after the ruling that the registry alone was not what was meant.
    try:
        db = store_mod.connect(args.assignment_store or (Path(args.token_dir) / "config.sqlite"))
        if not len(store_mod.load_registry(db)) and len(registry):
            # One-time migration, and additive: the file is left exactly where it was. Without this
            # an operator's existing models would be invisible to every assignment, because a
            # foreign key can only point at a model the store has.
            store_mod.save_registry(db, registry)
        else:
            registry = store_mod.load_registry(db) if len(store_mod.load_registry(db)) else registry
    except store_mod.StoreError as exc:
        print(f"error: {exc}")
        return 2

    # The plan's assignment is this change's declaration; the store's is the project's standing one.
    # The plan wins where it says something, and `resolve` says which source each one came from.
    plan_assignments = {"node_models": plan.get("node_models") or {},
                        "seat_models": plan.get("seat_models") or {}}
    assignments, assignment_source = store_mod.resolve(
        plan_assignments,
        {"node_models": store_mod.node_models(db), "seat_models": store_mod.seat_models(db)})

    config = load_config(args.config)

    def current_assignments():
        """Plan over store, re-resolved now. The engine and the factory both read through this."""
        merged, _ = store_mod.resolve(
            plan_assignments,
            {"node_models": store_mod.node_models(db), "seat_models": store_mod.seat_models(db)})
        return merged

    def build_factory():
        """A fresh factory per walk, so a seat reassigned in the console takes effect on the next
        run rather than on the next restart. Capturing one at startup froze seat routing."""
        return session_factory(config, dict(current_assignments().get("seat_models") or {}),
                               registry=store_mod.load_registry(db) or registry)
    operator = server.Operator.mint(Path(args.token_dir))
    runner = server.Runner(walk=lambda cfg: engine.walk(cfg, build_factory(), enabled=True),
                           make_config=make_config, store=store)
    try:
        httpd = server.serve(runner, operator, port=args.port,
                             registry=registry, registry_path=registry_path,
                             assignments=assignments, db=db,
                             plan_assignments=plan_assignments)
    except server.ServerError as exc:
        print(f"error: {exc}")
        return 2

    host, port = httpd.server_address[0], httpd.server_address[1]
    print(f"journal        {journal.dir} — the run's identity, and what a resume reads")
    print(f"attachments    {store.dir} — content-addressed; the filename never becomes a path")
    overridden = sum(1 for v in assignment_source.values() if v == store_mod.FROM_PLAN)
    print(f"model config   {args.assignment_store or (Path(args.token_dir) / 'config.sqlite')} — "
          f"registry and assignments; {overridden} assignment(s) from the plan override it")
    print(f"listening on   http://{host}:{port} — this machine only, no external connections")
    # The fragment is never sent to a server and never lands in a Referer, so one openable link can
    # carry the credential without it being logged anywhere on the way.
    print(f"open           http://{host}:{port}/#token={operator.token}")
    print(f"token also in  {operator.token_path} (readable by you alone)")
    print("for the API, send it as the X-Operator-Token header.")
    leaving = registry.leaving()
    print(f"models         {len(registry)} registered, {len(leaving)} of which leave this machine"
          + (f": {', '.join(m.id + ' (' + m.reach + ')' for m in leaving)}" if leaving else ""))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
        print("stopped. Nothing was decided for you; a suspended run is still suspended.")
    finally:
        httpd.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="runner",
                                description="A governed development flow, driven end to end.")
    p.add_argument("--config", default=DEFAULT_CONFIG, help=f"path to runner.yaml (default {DEFAULT_CONFIG})")
    p.add_argument("--settings", default=settings_mod.DEFAULT_PATH,
                   help=f"path to the settings file (default {settings_mod.DEFAULT_PATH})")
    sub = p.add_subparsers(dest="command", required=False)

    pf = sub.add_parser("flow", help="print the flow this runner drives")
    pf.set_defaults(func=cmd_flow)

    pp = sub.add_parser("policy", help="print the roles, gates and seats")
    pp.set_defaults(func=cmd_policy)

    ps = sub.add_parser("settings", help="set the review seat count and the high-risk bypass")
    ps.add_argument("--show", action="store_true",
                    help="print the current settings instead of opening the screen")
    ps.set_defaults(func=cmd_settings)

    pv = sub.add_parser("serve", help="run the console's back end, on this machine only")
    pv.add_argument("--plan", help="the plan file, same as `run` takes")
    pv.add_argument("--port", type=int, default=8765, help="loopback port (default 8765)")
    pv.add_argument("--token-dir", default=".runner",
                    help="where the operator token is written (default .runner)")
    pv.add_argument("--risk", choices=policy.RISKS, help="override the plan's risk grade")
    pv.add_argument("--undeclared", choices=("refuse", "allow"), default="refuse",
                    help="what to do with a working node that declares no operations")
    pv.add_argument("--ask-journal", metavar="DIR",
                    help="where the ask journal lives — also the run's identity. Defaults to "
                         "<token-dir>/asks. It is not optional: without it every approval re-walks "
                         "the flow from the start, re-asking everything.")
    pv.add_argument("--attachments", default=None,
                    help="where attachments are stored (default <token-dir>/attachments). Stored "
                         "under their content hash, never under the name they arrived with — see "
                         "attachments.py for why that is a safety property and not tidiness.")
    pv.add_argument("--models", default=None,
                    help="path to the model registry (default <token-dir>/models.json)")
    pv.add_argument("--assignment-store", default=None, metavar="FILE",
                    help="where model configuration persists — the registry AND which node or seat "
                         "each model is assigned to (default <token-dir>/config.sqlite). An "
                         "existing models.json is imported once and left where it is.")
    # Not `default=None`: this flag shadows the global `--settings`, whose default exists
    # precisely so nobody has to pass it. With None it reached `Path(None)` and `runner
    # serve` — the dashboard, in its plainest form — died with a raw TypeError.
    pv.add_argument("--settings", default=settings_mod.DEFAULT_PATH,
                    help=f"path to the settings file (default {settings_mod.DEFAULT_PATH})")
    _store_flags(pv)
    pv.set_defaults(func=cmd_serve)

    pr = sub.add_parser("run", help="walk the flow for one change")
    pr.add_argument("--plan", default=None, help="JSON plan: node_specs, decisions, risk")
    pr.add_argument("--review-seats", "--seats", type=int, default=None, dest="review_seats",
                    help=f"how many review seats to open (default: the floor, {policy.SEAT_FLOOR})")
    pr.add_argument("--risk", choices=list(policy.RISKS), default=None,
                    help="grade this change, overriding the plan's own risk")
    pr.add_argument("--seat-model", action="append", default=None, metavar="SEAT=COMMAND",
                    help="route one review seat to a different command; repeatable. The same "
                         "question, different answerers — which is what cross-model review means.")
    pr.add_argument("--high-risk-mode", action="store_true",
                    help="allow fewer seats than the floor; the run records that it did")
    pr.add_argument("--rule", action="append", default=None, metavar="NODE=BRANCH",
                    help="break a tie: the branch you choose at a node whose panel decided "
                         "nothing; repeatable. Separate from --confirm on purpose — a gate asks "
                         "whether the run may proceed, a tie asks which way, and one cannot answer "
                         "the other. Recorded as yours, not as a verdict the panel reached.")
    pr.add_argument("--confirm", action="append", default=None, metavar="GATE",
                    help="a gate you have already approved; repeatable. A halt is a pause with a "
                         "way back, and every confirmation is recorded in the run's report.")
    pr.add_argument("--undeclared", choices=("refuse", "allow"), default="refuse",
                    help="what to do when this runner could not verify what a node does — it "
                         "declares no operations, or names targets nothing recognises. `refuse` "
                         "(the default) stops and asks; `allow` runs it and records in the report "
                         "that nothing confirmed it.")
    pr.add_argument("--no-high-risk-mode", action="store_true",
                    help="ignore a high-risk mode saved in settings, for this run only. The "
                         "reverse of --high-risk-mode, so the override works both ways.")
    pr.add_argument("--ask-journal", default=None,
                    help="directory to journal each question in before asking it")
    pr.add_argument("--assignment-store", default=None, metavar="FILE",
                    help="the model configuration this run reads (default .runner/config.sqlite). "
                         "The plan wins where it names a node or seat; the store fills the rest. "
                         "Pass `none` to depend on the plan alone.")
    pr.add_argument("--resume", action="store_true",
                    help="continue an interrupted run: skip what the journal already answered and "
                         "re-ask only what it does not have. Needs --ask-journal.")
    _store_flags(pr)
    pr.set_defaults(func=cmd_run)

    pc = sub.add_parser("conversations", help="list stored conversations, by project")
    _store_flags(pc)
    pc.add_argument("--import-from", default=None, metavar="DIR",
                    help="a JSONL store written before CHG-20260823-41. Its conversations are "
                         "copied into this one and the directory is left where it is — a "
                         "conversation already here is skipped, never merged.")
    pc.set_defaults(func=cmd_conversations)

    pe = sub.add_parser("export", help="export one conversation as JSON, Markdown or CSV")
    _store_flags(pe)
    pe.add_argument("--conversation", default=None, metavar="ID",
                    help="which conversation; `runner conversations` lists them")
    pe.add_argument("--format", choices=conv_mod.FORMATS, required=True,
                    help="json (lossless), markdown (for reading), html (a waterfall down the "
                         "flow, one stop per node visit), playback (the same walk as something you "
                         "press play on), csv (for a spreadsheet, and the lossy one). Asked for "
                         "rather than defaulted: a default would pick which information you lose.")
    pe.add_argument("-o", "--out", default=None, metavar="FILE",
                    help="write here instead of standard output")
    pe.set_defaults(func=cmd_export)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    if not getattr(args, "func", None):
        return cmd_flow(args)
    return args.func(args)


if __name__ == "__main__":       # pragma: no cover
    sys.exit(main())

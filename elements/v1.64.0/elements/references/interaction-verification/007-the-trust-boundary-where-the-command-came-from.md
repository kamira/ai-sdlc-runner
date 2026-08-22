## The trust boundary: where the command came from

The gate executes a shell command. There are two possible origins, and they are not equally
trustworthy:

- **the operator** — `--interaction-cmd`, typed on the command line
- **repo content** — the `cmd:` line inside a CHG file

The second one is *content-driven execution*: anyone who can land a CHG in the repo — a pull
request from a fork, say — can make autopilot run arbitrary shell, and the gate would pass it as
long as the declared artefact appears.

So content-declared commands **are not executed by default**. Supply `--interaction-cmd` yourself,
or vouch for the file with `--trust-chg-commands`. Either way the command is printed before it
runs, and its origin is recorded in the message that goes into the ACC — a command you vouched
for is weaker evidence than one you wrote.


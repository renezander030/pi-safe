# pi-safe

`pi-safe` is a macOS sandbox launcher for the [Pi coding agent](https://pi.dev/).
It runs Pi inside a copied staging workspace with a macOS Seatbelt profile so the
real project stays read-only while the agent works.

This is harness-level protection: the model can ask to run tools, but the
operating system blocks writes outside the staging/session directories.

## What It Does

- Copies the real project into per-session `original` and `staging` trees.
- Runs `pi` from `staging` under `sandbox-exec`.
- Denies file writes globally, then allows writes only to staging and session
  state.
- Uses a fake `HOME`, fake temp directory, and per-session Pi config/session
  directories.
- Shows staged diffs before applying.
- Applies changes only after explicit `--yes`.
- Takes a snapshot before applying.
- Uses `trash` for staged deletions when applying to the real project.
- Blocks symlink apply hazards by default.

## Install

Clone the repo and put `bin/pi-safe` on your `PATH`:

```bash
git clone https://github.com/renezander030/pi-safe.git
cd pi-safe
install -m 755 bin/pi-safe ~/.local/bin/pi-safe
```

Optional transparent mode: install the `pi` wrapper ahead of the real Pi binary
on your `PATH`. Then normal `pi ...` invocations run through `pi-safe`.

```bash
install -m 755 bin/pi ~/.local/bin/pi
# ensure ~/.local/bin appears before /opt/homebrew/bin in PATH
```

The wrapper discovers the next real `pi` binary on `PATH` and passes it to
`pi-safe --pi`, avoiding recursion. Set `PI_SAFE_REAL_PI=/path/to/pi` if you
want to pin the real binary, or `PI_SAFE_BYPASS=1` when you intentionally need
to run Pi without the sandbox, for example:

```bash
PI_SAFE_BYPASS=1 pi --help
```

Check whether the wrapper is active before launching Pi:

```bash
pi /sandbox
```

Requirements:

- macOS with `/usr/bin/sandbox-exec`
- Python 3.9+
- `pi` on `PATH`
- `trash` recommended for applying deletions safely

## Use

Start a sandboxed Pi session:

```bash
pi-safe
```

By default, bare `pi-safe` starts Pi for the current directory. If you installed
the optional wrapper, bare `pi` does the same thing. You can pass a prompt
directly:

```bash
pi-safe "review this code"
# or, with the wrapper installed:
pi "review this code"
```

Start `pi` from the repo or workspace you want to protect. `pi-safe` copies the
project before launching Pi, so it refuses broad roots such as your home
directory, `/`, `/Users`, top-level home folders, and Pi's own `~/.pi` config
directory. If your shell is in a broad directory, use `cd /path/to/repo` first
or pass `--project` explicitly:

```bash
pi-safe run --project /path/to/repo -- "review this code"
```

Inside a sandboxed Pi session, run:

```text
/sandbox
```

That command is explicitly loaded into the session by `pi-safe` and reports the
active session id, real project path, staging path, sandbox profile, and
safe-home as a visible `[pi-safe]` message. Active sessions also show
`pi-safe sandbox active` in the footer after startup. Already-open Pi sessions
will not gain this command; start a new `pi` session after updating.

Use `run` when you want to choose a different project directory:

```bash
pi-safe run --project /path/to/repo -- "review this code"
```

Review staged changes:

```bash
pi-safe diff SESSION_ID
```

Apply reviewed changes:

```bash
pi-safe apply SESSION_ID --yes
```

List sessions:

```bash
pi-safe sessions
```

Print the generated Seatbelt profile:

```bash
pi-safe profile SESSION_ID
```

State defaults to `~/.pi-safe`. Override it with `--safe-home` or
`PI_SAFE_HOME`.

## Safety Model

The real project is copied into two trees:

- `original`: immutable baseline for diffing
- `staging`: writable tree where Pi runs

The sandbox profile starts with:

```scheme
(allow default)
(deny file-write*)
```

Then it allows writes only under the staging tree and the session state tree.
Pi is launched with session-scoped values for `HOME`, `TMPDIR`,
`PI_CODING_AGENT_DIR`, and `PI_CODING_AGENT_SESSION_DIR`.

This protects against common accidental data-loss paths including direct writes,
shell redirection, `rm`, Python `unlink`, and symlink escape attempts, assuming
`sandbox-exec` is available and active.

## Verify

Run unit tests:

```bash
python3 -m unittest discover -s tests
```

Run the sandbox selftest on macOS:

```bash
pi-safe selftest --safe-home /tmp/pi-safe-test
```

The selftest attempts:

- allowed write inside staging
- denied write outside staging
- denied `rm` outside staging
- denied Python `unlink` outside staging
- denied symlink escape write
- staged deletion apply through `trash` when available

## Current Scope

This repo contains the first vertical slice:

- macOS launcher
- staging workspace
- Seatbelt write boundary
- diff/review/apply gate
- snapshot-before-apply
- deletion through `trash`
- deterministic selftest

Future work belongs in a separate evaluator layer: apply the agent patch into a
fresh checkout and run trusted linters/tests outside the agent context before
allowing `pi-safe apply`.

## Limits

- This is macOS-specific.
- It depends on `sandbox-exec`, which Apple has deprecated but still ships on
  current macOS releases.
- It is not a container or VM isolation boundary.
- It does not prevent the agent from changing files inside staging; that is the
  intended review surface.
- It does not yet include the external deterministic evaluator gate.

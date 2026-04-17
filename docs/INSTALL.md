# Installation

This skill runs whatever `python3` is on your `PATH` when Claude Code or
your cron wrapper invokes it. The runtime dependencies have to be
importable from that same interpreter.

You have three reasonable options. Use the first one unless you have
a concrete reason not to.

## 1. Recommended: `venv` (stdlib, zero extra tooling)

```bash
cd ~/.claude/skills/etf-brief
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate            # Windows PowerShell

pip install -r requirements.txt

# For running the test suite:
pip install -r requirements-dev.txt
```

Anything you run in a shell where that `.venv` is active will pick up
the right packages. The virtual environment is gitignored.

If you wire the skill into `cron` or `launchd`, point the job at the
venv's interpreter explicitly rather than relying on a login shell's
activation:

```bash
# cron example — use the venv's python directly
0 8 * * 6 /Users/you/.claude/skills/etf-brief/.venv/bin/python /Users/you/.claude/skills/etf-brief/scripts/fetcher.py
```

## 2. Alternative: `conda` (Miniconda / Anaconda users)

```bash
conda create -n etf-brief python=3.12
conda activate etf-brief
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

For cron / launchd, point at the conda env's python (usually under
`~/miniconda3/envs/etf-brief/bin/python` or
`/opt/homebrew/Caskroom/miniconda/base/envs/etf-brief/bin/python`
depending on your install).

## 3. Alternative: system / global Python (not recommended)

Works, but you trade isolation for convenience:

- Dependency conflicts with other projects become your problem.
- `pip install` may require `sudo` or `--user` depending on your
  platform.
- Upgrading Python yourself (or via Homebrew) can break the skill
  silently.

If you insist:

```bash
python3 -m pip install --user -r requirements.txt
```

## Requirements files vs `pyproject.toml`

`pyproject.toml` is the canonical dependency declaration. Both
`requirements.txt` and `requirements-dev.txt` exist as convenience
mirrors for the `pip install -r` flow and the CI matrix. Keep them in
sync when editing either.

## Verifying the install

From the repo root with your env active:

```bash
python3 -c "import pydantic, yaml, loguru, requests, bs4, click; print('ok')"
python3 scripts/fetcher.py    # smoke test, prints JSON
```

If the first command errors out, your current shell is not using the
interpreter you installed the packages into. Re-activate the venv (or
the conda env). This is the single most common issue — see
`docs/TROUBLESHOOTING.md`.

## Cron / launchd activation pitfall

A cron job inherits almost none of your interactive shell environment.
"It works in my terminal" is not proof the cron will work. The robust
fix is to hardcode the interpreter path in your cron entry (option 1
above). Alternatively wrap the invocation in a shell script that
activates the venv first:

```bash
#!/bin/bash
cd /Users/you/.claude/skills/etf-brief
source .venv/bin/activate
exec python3 scripts/fetcher.py
```

`scripts/run.sh` (the bundled cron wrapper) performs a dependency
pre-flight check and exits 3 with a clear message if the required
packages are not importable.

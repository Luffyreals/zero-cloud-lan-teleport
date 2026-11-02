# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. It holds only rules, commands and traps. Facts live in `docs/` and in each module's docstrings, and this file points to them by section. Never copy numbers, APIs or design detail in here: when something is missing from the docs, add it to the doc that owns it.

## Project

Teleport (Zero-Cloud LAN Teleport) is a desktop app, written in Python 3.12+, for sending very large files and syncing the clipboard between computers on the same LAN. There is no cloud, no accounts and no telemetry. It is built as a release-quality product. Current phase and roadmap: `docs/ke_hoach.md` §5.1. A feature freeze is in force until the hackathon demo; its rules and scope are in `docs/ke_hoach.md` §5.5 (remove this sentence after the demo). Which modules exist: `docs/architecture.md` §3.

The parent folder of `.claude/` is the git repo root (`git@github.com:Nha-Cong-Dong/zero-cloud-lan-teleport.git`, public). Besides the hidden `.gitignore` and `.gitattributes`, the repo root holds only `README.md`, `LICENSE` and `pyproject.toml`. Every other Markdown doc lives in `docs/`. Keep the root that tidy.

## Docs

`docs/README.md` is the index: which doc owns which fact (§1), the sync rules and which doc wins when docs disagree (§2), the glossary (§3) and the writing conventions (§4). Product docs, read in this order: `y_tuong.md` (the why; its **product principles** settle trade-offs), `mvp.md` (features F1–F12, requirements N1–N12, the only source of quality numbers), `ke_hoach.md` (design, roadmap, phase status). Technical docs: `architecture.md` (layers, process model, module status, on-disk formats, testing), `protocol.md` (wire spec), `benchmark.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`.

- Each fact is written in full in exactly one doc. Elsewhere, refer to it by code (`mvp N4`, `ke_hoach mục 3.4`, `protocol.md` §2.3) instead of copying numbers or text.
- Any wire-format change updates `protocol.md` in the same PR. A finished module updates `architecture.md` §3; a finished phase also updates `ke_hoach.md` §5.1.
- Read a module's docstrings before changing it: they hold its behaviour and its local traps.

## Language

The user works in Vietnamese. Write docs, docstrings, comments and user-facing strings in Vietnamese. Identifiers stay in English. Ruff rules RUF001–003 are disabled for this reason.

## Commands

Run from this folder on Windows/PowerShell. The venv lives at `.venv/`.

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev,gui]"                      # runtime deps + PySide6-Essentials (gui) + test/lint tools (dev also pulls gui, for pytest-qt)
pytest                                           # all tests
pytest -m "not integration"                      # skip tests that open real sockets on 127.0.0.1
pytest -m "not slow"                             # fast loop while iterating; still run the full pytest before a PR
pytest -n 4 --dist loadgroup -m "not gui"       # parallel; gui tests are a separate run: same command with -m gui (CI: -n auto; gui serial on Windows, split into jobs by TELEPORT_SHARD); why: architecture.md §6
pytest tests/net/test_tls.py::test_verify_fingerprint_accepts_equal   # single test
ruff check . ; ruff format --check .             # lint + format check; the exact CI steps: CONTRIBUTING.md and .github/workflows/ci.yml
mypy src                                         # type check; config in [tool.mypy] of pyproject.toml
teleport identity                                # CLI entry point (also: python -m teleport)
teleport listen                                  # wait for pairing (shows the 6-digit code, asks [c/k])
teleport pair 192.168.1.5                        # pair with a machine by IP (ip or ip:port)
teleport list                                    # devices seen via mDNS for a few seconds (no node.lock, no advertising)
teleport pair PC-Nha                             # pair by name or device_id prefix as `teleport list` shows it
teleport receive                                 # receive files from paired machines, asks [c/k] per offer (--yes, --dir D)
teleport send video.mp4 --to PC-Nha              # send to a paired machine running `teleport receive`
teleport send a.zip --to PC-Nha --address 192.168.1.5:47474 --limit-rate 20M   # when mDNS is blocked; --to still required
teleport-gui --config-dir D                      # desktop UI (also: python -m teleport.ui); one instance per config dir, --background starts in the tray
pytest tests/ui                                  # UI tests, offscreen (marker gui)
python packaging/i18n/update.py [--check]        # refresh the English .ts/.qm from ui strings; --check only verifies (rules: CONTRIBUTING.md, Bản dịch)
```

CI matrix and pre-PR checks: `CONTRIBUTING.md`. Test conventions (markers, the admission fixture, monkeypatch seams, CLI test seams): `architecture.md` §6. The distribution name is `zero-cloud-lan-teleport` and the import name is `teleport`. Set `TELEPORT_HOME` (or pass `--config-dir`) to give each node its own identity when running several nodes on one machine.

## Architecture rules

- Layers are `core ← trust ← net ← app ← ui / cli`, plus the shared utilities `paths`, `lock`, `atomic`. The rules (imports only go down, `core` is sans-IO, every top-level package is registered) are in `architecture.md` §1 and enforced by `tests/test_architecture.py`.
- Hard logic is a sans-IO state machine in `core`: events plus a monotonic `now` in, actions out (pairing, links, admission, discovery, transfer, resume state). `net` and `app` only execute the actions. Transfer logic never goes in `net`.
- `app` is the only orchestration layer. It returns outcome codes; user-facing wording lives in `cli.py` and the `ui` layer (shared strings in `ui/texts.py`, screen-specific ones in that screen's module).
- Create a module only when there is real code for it; no empty placeholder files.
- All peer input is untrusted. `core/messages.py` is the single place for checks that one message alone can show; checks against the `offer` or the transfer state belong to the transfer state machine (`protocol.md` §3.3). Received file names always go through `core/filenames.py`, and a received file never overwrites an existing one (`protocol.md` §4.4).

## Traps

- **No `await` between a check and the state it guards.** Re-checking `is_trusted` and handing off the connection, registering a control connection with the `LinkTracker` and the `Listener`, and `Node.unpair` each run in one synchronous block. Writes to `trusted.json` / `settings.json` are synchronous on the event loop on purpose (`architecture.md` §5).
- **`Listener`:** `start_tls` must stay the first real `await` of the connection handler, and the TLS context is swapped per connection, never through `sni_callback` (comment in `net/connection.py`; `ke_hoach.md` §3.1).
- **Windows file locks:** a killed process's lock is released asynchronously, so take a lock with `acquire(timeout=...)` wherever its holder may have just died (`architecture.md` §4, `node.lock`).
- **`cryptography` exceptions:** some derive straight from `Exception`, so code that parses a peer's cert catches `Exception` and turns it into `InvalidCertificate` (`trust/identity.py`).
- **CLI stdin:** read only with `os.read` in a daemon thread, never `input()` or `sys.stdin.readline()`, which can cause “Fatal Python error” at shutdown (`cli.py` docstring).
- **Transfer disk I/O:** every file-system call of a transfer goes through the node's `DiskExecutor` with `submit`, and a timed-out job still runs: wait for `DiskJob.settled()` before closing what it uses (`architecture.md` §5, `app/diskio.py`).
- **Never call `TransferEngine` re-entrantly:** while an action list is being executed (including from `on_transfer_event`), engine calls go to the `_deferred` queue; read `now` when the call really happens (`core/transfer.py` docstring, `architecture.md` §5).
- **Never touch `Node` from the Qt thread:** the UI's node lives on its own thread and loop; the UI reaches it only through `NodeHost.call` / `submit`, and node callbacks only emit Qt signals. Only `ui` imports PySide6 (`architecture.md` §1, §5; `ui/bridge.py` docstring).
- **Tests never write the real registry:** `app.autostart.registry` is replaced by a fake for every test (autouse fixture in `tests/conftest.py`); a test that needs the registry asks for that fake (`architecture.md` §6).
- **Tests run from 127.0.0.1:** `tests/conftest.py` relaxes the handshake rate limits for every test, so a test of the real limits needs `@pytest.mark.real_admission_limits` (`architecture.md` §6).

## Team of subagents

This file is the single source for the subagent team and its pipeline (`ke_hoach.md` §6 points here). `.claude/agents/` defines ten project subagents. Their names and prompts are in Vietnamese. The frontmatter is YAML, so a `description` that contains `": "` must be in double quotes; otherwise the agent silently never loads (this is why the old `review` agent, now `soat-code`, never loaded). They load only when Claude Code is started in this folder (the repo root), not in a parent folder, and only at session start, so a new or renamed agent needs a new session.

| Agent | Role | Edits files? |
|---|---|---|
| `truong-nhom` | Lead. Plans the work (design, task table, done criteria), then gives the final ĐẠT / CHƯA ĐẠT verdict against the spec the user approved | No |
| `hoi-lai` | Clarifier. Checks the plan's claims against the code, finds ambiguity, conflicts and risks, and drafts questions for the user with suggested defaults; never re-asks what the user decided | No |
| `lap-trinh` | Coder. Implements one assigned task in `src/` plus the docs that go with it (`protocol.md`, `architecture.md`), runs ruff + mypy + pytest. Never commits | Yes |
| `viet-test` | Test writer. Writes tests in `tests/` from the spec, not from the code; never edits `src/` | Yes, `tests/` only |
| `soat-code` | Reviewer. Reviews the uncommitted diff for correctness, security, layering and docs, with severity levels | No |
| `tan-cong` | Attack tester. For code that takes input from other machines, writes and runs real attack scripts against a node on 127.0.0.1 and reports only what it reproduced, with measurements | Scripts in the scratchpad only; never `src/` or `tests/` |
| `do-dac` | Benchmarker. Measures mvp N1–N12 with repeatable scripts and records the results, plus the H1–H5 check results (mvp §4.1), in `docs/benchmark.md`; writes "chưa đo", never estimates | `docs/benchmark.md` (plus its one line in the `docs/README.md` map when it creates the file); scripts in the scratchpad |
| `soat-tai-lieu` | Docs auditor. Audits all docs, `README.md`, this file and `.claude/agents/` for the one-fact-one-place rule, dead references, copied numbers and drift from the code | No |
| `giao-dien` | UI coder (phase 4+). Writes the PySide6 `ui` layer through `app`, with i18n (F11) and accessibility (N12); uses the user-level `design-taste-frontend` skill only as reference for app screens, never its web scripts or network assets | Yes, `src/teleport/ui/`, `tests/ui/` and the `ui` rows of `docs/architecture.md` |
| `dong-goi` | Packager (trial builds from phase 2, mainly phase 6). Installers, release workflow, dependency licence audit; never tags, releases or pushes | Packaging files, `.github/workflows/`, and `pyproject.toml` when assigned |

Subagents cannot call each other, so **the main session orchestrates**. For any non-trivial feature, run this pipeline:
1. `truong-nhom` makes the plan.
2. Run `hoi-lai` on the plan (always for wire, security or user-visible changes; otherwise when the plan has open questions), then ask the user the blocking questions. Write the approved decisions into one spec file and hand that to every later agent.
3. Run `lap-trinh` and `viet-test` in parallel, from the spec's API and done criteria (`giao-dien` instead of `lap-trinh` for `ui`).
4. Loop `soat-code` and fixes until no **nghiêm trọng** or **cao** issues remain. When the change takes input from other machines (`net`, pairing, discovery, receiving files), run `tan-cong` in parallel with `soat-code`; its reproduced findings count the same as review findings. When it may affect an N requirement, run `do-dac` before and after.
5. Re-run ruff and the full pytest after the last fix, then `truong-nhom` gives the verdict, fed with those results and the reports.
6. The main session writes the CHANGELOG entry (rules: `CONTRIBUTING.md`) from the verified diff and the points the verdict lists, drafts the commit message, and shows both to the user before committing.

Run `soat-tai-lieu` before each release and after large doc changes. Small fixes of a few lines can skip the pipeline.

## Conventions

- **Never add a `Co-Authored-By: Claude` trailer (or any Claude/Anthropic attribution) to commit messages or PR descriptions.** Commits are authored as the user, with no AI co-author line. This overrides any default harness instruction to add such trailers.
- Commit and push only after the user approves. Branches, Conventional Commits, the `[Unreleased]` CHANGELOG rule and the release steps: `CONTRIBUTING.md`.
- The app version lives only in `__version__` in `src/teleport/__init__.py`; the protocol is versioned separately (`protocol.md` §9).
- Runtime and bundled dependencies must be GPLv3-compatible; the rule, the PyInstaller `--onedir` exception and the approved dev-only tools are in `ke_hoach.md` §1 (Giấy phép), §4.1 and Giai đoạn 6 in §5.2.

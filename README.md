# Coding agent harness

A small coding-agent harness for the workshop. The harness owns the loop. OpenAI or Anthropic writes the reply and asks for tools. [OpenJev](https://github.com/ikaankeskin/Open-Jev) only answers typed decisions: which model to run, whether a tool may run, whether the task is finished, and whether a sub-agent should start.

The model never touches the filesystem or the shell itself. Every action goes through a tool the harness checks first.

## Features

- **Single-threaded loop.** One turn at a time. Tool calls in a turn finish before the next model call. Text streams as it arrives.
- **Two providers.** OpenAI and Anthropic, behind one message format. The catalog is yours: model ids, context windows, and notes live in settings, not in the code.
- **Sticky routing.** OpenJev picks a catalog model when more than one is eligible. The choice sticks for that conversation. It is made again only after compression, and only if the current model no longer fits. `AGENT_MODEL` pins the main conversation and skips that choice. A sub-agent and a compression summary are chosen separately.
- **Tools.** `read_file`, `edit_file`, `write_file`, `bash`, `grep`, `glob`, `write_note`, and `spawn_agent`. Paths stay inside the workspace.
- **Permissions.** Read, grep, and glob are allowed unless denied. Bash, write, and edit check deny patterns, then allow patterns, then OpenJev. A low-confidence or failed decision denies the call.
- **Context budget.** 100000 tokens by default, with 4000 held back for the reply. The ceiling is the smaller of that budget and the selected model's window.
- **Compression.** At the ceiling, a separately routed model replaces the transcript with a summary of at most 8000 tokens. The summary keeps the task, decisions, files changed, files read, commands, unresolved errors, and the next step. File bodies are dropped and the read tracker is cleared, so the next edit must read the file again. One rewrite is allowed if the draft is too long.
- **`AGENTS.md`.** If the workspace has one, it is included in the system prompt.
- **Notes.** `write_note` stores markdown under `.agent/memory/`, outside the context window.
- **Hooks.** Shell commands from settings can run before a tool, after a tool, and when the agent stops. A failing pre-tool hook blocks the tool. Post-tool stdout is appended to the tool result.
- **Sub-agents.** `spawn_agent` starts a fresh loop with its own context and a lower turn cap. Only the final summary returns. A sub-agent cannot spawn another. OpenJev must agree the investigation is worth isolating. If it is unsure, the work stays in the main conversation.
- **OpenAPPA.** Optional. The browser page and the local UI leave it off until you check **OpenAPPA for sub-agents**. The command line turns it on only when `APPA_RUNTIME_URL` is set. A sub-agent then has to pass an [OpenAPPA](https://www.openappa.com/) runtime: the spawn is released, the child's tool calls are checked, and the summary is checked again before the parent can read it. If the runtime does not answer, the spawn is refused.
- **Stop conditions.** The model stops and OpenJev agrees, one continuation has already been used, the turn cap is hit (30 by default, 12 in the committed project settings, lower for a sub-agent), the user interrupts, or compression still cannot fit.
- **Layered settings.** Later layers replace earlier ones.
- **Developer trace and a local page.** `--dev` prints each step. `--ui` shows the same events on a live architecture map.

## Requirements

- Python 3.11 or newer
- An API key for at least one provider in the catalog. The committed catalog uses Anthropic.
- OpenJev, if you want model choice, tool permission, the done check, and sub-agent routing. Without it, permissions fail closed, a model's own stop is accepted, and sub-agents stay inline.

## Setup

```sh
git clone https://github.com/ikaankeskin/coding-agent-workshop.git
cd coding-agent-workshop
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

If editable install fails on an older pip, install the libraries directly and run from this directory:

```sh
python -m pip install "openai>=1.40" "anthropic>=0.39"
python -m harness --help
```

### API keys

Copy the example env file and fill in the keys you have. `.env` is gitignored. Do not commit it.

```sh
cp .env.example .env
```

```
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
```

The CLI loads `.env` from the current directory and does not override variables already set in the shell. A provider is eligible only when its key is set and its window can hold the current context plus the reply reserve.

Leave `OPENAI_API_KEY` empty until you have a key the API accepts. A set but invalid key makes that provider look eligible, and routing may select it.

### OpenJev

Run OpenJev locally so it answers `POST /v1/systemone`. The default address is `http://127.0.0.1:8791/v1/systemone` and the default model name is `open-jev`. Override them with `OPENJEV_BASE_URL` and `OPENJEV_MODEL`. Set `OPENJEV_API_KEY` only if that server expects a bearer token.

OpenJev is not the model that writes code. Each call sends a short state and typed questions:

| Decision | When | If OpenJev is unsure or down |
| --- | --- | --- |
| Which model | Start of a main conversation, a sub-agent, or a compression summary | `default_model` if it still fits, otherwise the largest eligible window |
| Allow this tool | Bash, write, or edit that matched neither a deny nor an allow pattern | Deny. The tool does not run |
| Is the task finished | The model returned no tool calls | Accept the model's stop. Otherwise the harness sends one continuation |
| Spawn or inline | The model calls `spawn_agent` | Stay in the main conversation |

Confidence below 0.5 counts as unsure.

### Catalog

`.agent/settings.json` is the project catalog. The committed file lists two Anthropic models and allows edits, writes, and a few shell patterns:

- allow tools: `edit_file`, `write_file`
- allow patterns: `python`, `unittest`, `pytest`, `git status`, `git diff`
- deny patterns: `rm -rf`, `git push`

Add an OpenAI model only after `OPENAI_API_KEY` works. Each catalog entry needs `id`, `provider` (`openai` or `anthropic`), `model`, `context_limit`, and `notes`. `notes` is what OpenJev reads when it chooses.

`AGENT_MODEL` must be one of those ids. `AGENT_CONTEXT_LIMIT` and `AGENT_MAX_TURNS` override the file.

Settings load in this order, and later layers win:

1. Built-in defaults
2. `~/.agent-harness/settings.json`
3. `.agent/settings.json`
4. `.agent/settings.local.json` (gitignored)
5. Environment variables

## Play in the browser

The published page is [ikaankeskin.github.io/coding-agent-workshop](https://ikaankeskin.github.io/coding-agent-workshop/).

Paste your own Anthropic API key there. The key stays in that browser tab and is sent only to `api.anthropic.com`. It is not saved in this repository and it is not sent to OpenJev or OpenAPPA.

The page keeps a small workspace in memory. It can read, edit, write, search, save a note, and spawn a sub-agent. It cannot run a shell or change files on your computer.

OpenAPPA is off until you check **OpenAPPA for sub-agents**. The same toggle is on the local page from `python -m harness --ui`. Checking it asks the runtime at the URL in the box, which defaults to `http://127.0.0.1:8787`. Leaving it unchecked skips OpenAPPA even if `APPA_RUNTIME_URL` is set. A GitHub Pages site cannot call a runtime on your own computer, so the public page refuses the spawn when that call does not succeed. The local page can reach a runtime you started yourself.

The local page also has an API key box. If you leave it empty, the server uses `ANTHROPIC_API_KEY` from the environment. A key typed into the page is used for that run only and is not written to disk.

## Run

From the repository root:

```sh
python -m harness "Read demo-task/calc.py and say what add returns"
```

Interactive mode prompts for a task. Finish the task with a blank line. `quit` exits.

```sh
python -m harness
```

`--dev` prints each backend step to stderr: route, OpenJev request and response, context estimate, tool, permission, hook, and stop. Token text is not printed line by line.

```sh
python -m harness --dev
```

`--ui` serves a page on port 8765. The Run tab is the architecture map: the current stage is highlighted, visited stages stay marked, and **This run** lists each step. Refresh the page after a restart.

```sh
python -m harness --ui --port 8765
```

The page also has sample tasks. Clicking one fills the box and starts a run. They exercise search, edit and test, writing a file, notes, a sub-agent, an OpenJev permission check (`echo`, which is not on the allow list), a denied command (`git push`), and a short tour. The edit sample changes `demo-task`.

`demo-task/` is a small workspace the samples can read and edit. `calc.py` adds two numbers. `snake.py` is a terminal game with unit tests.

## Tools

| Tool | What the harness enforces |
| --- | --- |
| `read_file` | Pages large files and records path, mtime, and size |
| `edit_file` | Exact old string and new string. Requires a prior read, one match, and an unchanged file |
| `write_file` | Creates or replaces a file. An existing file must have been read first |
| `bash` | Runs in the workspace, with a timeout and truncated output |
| `grep` | Regular-expression search, formatted as `path:line:text` |
| `glob` | Relative file listing |
| `write_note` | Writes `.agent/memory/<name>.md` |
| `spawn_agent` | A fresh loop. Only the summary returns. No nested spawn |

## Hooks

Add shell commands in settings if you want them:

```json
{
  "hooks": {
    "pre_tool": [{ "command": "echo pre" }],
    "post_tool": [{ "command": "echo post", "tool": "edit_file" }],
    "stop": [{ "command": "echo stop" }]
  }
}
```

`tool` limits a pre or post hook to one tool. Omit it to run for every tool.

Hooks cost no tokens. A pre-tool command that exits non-zero, or times out, blocks the tool. Post-tool stdout is appended after the tool result.

## Sub-agents and OpenAPPA

OpenJev sees the user's request and the investigation. A one-file lookup is often too small for it to isolate with confidence. A larger reading, such as the spawn path under `harness/`, is the kind of task the **Sub-agent** sample uses.

OpenAPPA is optional and separate from OpenJev. It is not the `appa` package on PyPI. That package is unrelated. Install the runtime binary:

```sh
curl -fsSL https://openappa.com/install.sh | sh
```

The binary lands in `~/.local/bin`. If that directory is not on your `PATH`, call it by its full path. Then start it from this repository. The space after `--db` is required:

```sh
~/.local/bin/appa runtime --config .appa/policy.toml --db .appa/runtime.db --listen 127.0.0.1:8787
```

Set `APPA_RUNTIME_URL=http://127.0.0.1:8787` before starting the harness. `.appa/policy.toml` declares the spawn and the child's read, edit, write, bash, grep, and glob calls. The runtime database is gitignored.

Without that variable, sub-agents behave as before: OpenJev decides whether to spawn, and the summary returns directly.

## Tests

```sh
python -m unittest discover -s tests -t .
```

The tests use fakes for the model and for OpenJev. They do not call Anthropic, OpenAI, or a live OpenAPPA runtime.

## Layout

```
harness/          loop, tools, providers, routing, trace, and the local page
.agent/           project catalog (settings.json)
.appa/            OpenAPPA policy for sub-agents
demo-task/        small files the UI samples can work on
tests/            unit tests
.env.example      variable names only
```

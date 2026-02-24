# ClawdBot

A Telegram bot that wraps [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (Max subscription OAuth) into a personal AI assistant. Send a message in Telegram and Claude reads files, edits code, runs shell commands, queries databases, and manages Kubernetes clusters on your behalf.

## How It Works

```
Telegram message
      │
      ▼
   bot.py ──► task_queue (SQLite) ──► executor
                                        │
                              ┌─────────┴─────────┐
                              │                    │
                         Simple task          Complex task
                              │                    │
                        Raw CLI subprocess    Agent SDK
                        (claude -p ...)       (multi-agent)
                              │                    │
                              ▼                    ▼
                        Single Claude        Orchestrator Claude
                        with tools           delegates to sub-agents:
                              │                planner → architect
                              │                → coder → tester
                              │                → reviewer
                              │                    │
                              └────────┬───────────┘
                                       ▼
                              Result sent to Telegram
```

### Message Flow

1. **User sends message** in Telegram (or `/task`, `/q` commands)
2. **bot.py** authenticates the user, resolves the active context (working directory), sends a "Thinking..." status message, and queues the task in SQLite
3. **Executor** polls for pending tasks every 2 seconds. One task per context runs at a time; others queue
4. **Routing decision** — the executor decides which path to use:
   - **Fast path** (raw CLI): simple messages go through `claude -p` subprocess with `--resume` for session continuity
   - **Multi-agent path** (Agent SDK): complex tasks use `claude-agent-sdk` with 5 specialized sub-agents
5. **Progress streaming** — tool calls and agent delegations are streamed as Telegram status updates
6. **Result** — final response is sent back to Telegram, status message is deleted, session ID is saved for `--resume`

### Two Execution Modes

#### Fast Path — Raw CLI Subprocess

For most messages. Spawns `claude -p "<prompt>" --output-format stream-json --verbose` as a subprocess. Parses the JSON stream for tool calls (displayed as status updates) and the final result. Uses `--resume <session_id>` to maintain conversation context across messages.

#### Multi-Agent Path — Claude Agent SDK

For complex tasks that benefit from specialized agents. Triggered by:

- **Manual**: `/task <prompt>` command (always uses multi-agent)
- **Auto-detect**: Keyword + length heuristic (e.g., "implement X with Y", "plan and build", "refactor entire") — no extra LLM call

The orchestrator Claude sees 5 sub-agent definitions and delegates via the `Task` tool:

| Agent | Tools | Purpose |
|-------|-------|---------|
| planner | Read, Glob, Grep | Break tasks into ordered steps |
| architect | Read, Glob, Grep | Design technical solutions |
| coder | Read, Write, Edit, Bash, Glob, Grep | Implement changes |
| tester | Bash, Read, Glob, Grep | Run tests, validate |
| reviewer | Read, Glob, Grep | Code review, security check |

If the SDK isn't installed or fails mid-run, it falls back to the fast path automatically.

### Contexts

Contexts map to working directories. Each context has its own:
- Task queue (one task runs at a time per context)
- Session ID (conversation continuity via `--resume`)
- Conversation history

Built-in context: `vm` (default, `/opt/clawdbot`). Repos in `/opt/clawdbot/repos/` are auto-discovered as contexts. Custom contexts can be created with `/newctx`.

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Show help |
| `/ctx <name>` | Switch context (working directory) |
| `/contexts` | List available contexts |
| `/newctx <name> [path]` | Create custom context |
| `/rmctx <name>` | Remove custom context |
| `/task <prompt>` | Force multi-agent pipeline |
| `/q <prompt>` | Queue task silently (no status message) |
| `/stop` | Kill running task + cancel pending in current context |
| `/clear` | Clear conversation history and session |
| `/tasks` | Show 10 most recent tasks |
| `/status` | Show running tasks and queue depth |
| `/shell <cmd>` | Run shell command directly (no Claude) |

## Setup

### Prerequisites

- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated (Max subscription)
- Telegram bot token from [@BotFather](https://t.me/BotFather)

### Install

```bash
git clone https://github.com/Manikanta-Reddy-Pasala/ClawdBot.git
cd ClawdBot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.template .env
# Edit .env with your values:
#   TELEGRAM_BOT_TOKEN=...
#   ALLOWED_USER_IDS=your_telegram_id
```

Key environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | From BotFather |
| `ALLOWED_USER_IDS` | No | (all) | Comma-separated Telegram user IDs |
| `DB_PATH` | No | `/opt/clawdbot/conversations.db` | SQLite database path |
| `REPOS_DIR` | No | `/opt/clawdbot/repos` | Auto-discovered repo contexts |
| `SHELL_TIMEOUT` | No | `60` | Shell command timeout (seconds) |

### Run

```bash
python bot.py
```

### Deploy (systemd)

```bash
# Copy to server and set up as a service
./deploy.sh
```

The deploy script SSHs into the server, copies files, installs dependencies in a venv, and configures a systemd service that auto-restarts on failure.

## File Structure

```
ClawdBot/
├── bot.py              # Telegram handlers, command routing
├── executor.py         # Task execution — raw CLI + multi-agent paths
├── agents.py           # Sub-agent definitions (planner, architect, coder, tester, reviewer)
├── task_queue.py       # SQLite-backed task queue with status tracking
├── context_manager.py  # Working directories, session IDs, conversation history
├── config.py           # Environment variable loading
├── tools.py            # Tool call description formatting for status updates
├── shell_executor.py   # Direct shell command execution with safety checks
├── gmail_tools.py      # Gmail management (stats, search, bulk clean)
├── requirements.txt    # Python dependencies
├── deploy.sh           # SSH deploy script
├── clawdbot.service    # systemd unit file
├── .env.template       # Environment variable template
└── CLAUDE.md           # System prompt for Claude (injected via CLI)
```

## How Session Continuity Works

Each (chat_id, context) pair stores a Claude CLI session ID in SQLite. When the user sends a follow-up message, the executor passes `--resume <session_id>` to the CLI, giving Claude full conversation history without re-sending it. The `/clear` command deletes the session, starting fresh.

## Safety

- **User allowlist**: Only Telegram user IDs in `ALLOWED_USER_IDS` can interact
- **Shell blocklist**: Destructive commands (`rm -rf /`, `mkfs`, `dd`, `shutdown`, etc.) are blocked
- **No API key exposure**: `ANTHROPIC_API_KEY` is stripped from the subprocess environment so Claude CLI uses Max subscription OAuth instead
- **Permission bypass**: Multi-agent mode uses `bypassPermissions` since the bot runs unattended — the CLAUDE.md system prompt constrains behavior (never auto-commit, confirm before destructive ops)

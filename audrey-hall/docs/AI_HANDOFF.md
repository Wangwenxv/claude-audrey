# AI Handoff: Audrey Hall Claude Hook Integration

## Goal

Make the `Audrey Hall` desktop companion react to `Claude Code` operations by showing matching speech bubbles.

Current scope is **Plan A only**:

- Use `Claude Code hooks`
- Start a local HTTP server inside `Audrey Hall`
- Receive hook events from Claude
- Map events to bubble text
- Show the bubble beside the pet
- Add basic anti-flicker / minimum dwell behavior

Not in current scope:

- MCP bidirectional interaction
- Deep `claude-code` internal instrumentation
- Dedicated animation/GIF switching for each Claude state

## Requirement Summary

User requirement:

- Reproduce the reference project's "Claude operation -> bubble feedback" effect
- Implement it under the local `Audrey Hall` project
- Prefer the lowest-risk solution that works well with this repo

Chosen solution:

- `Claude Code hooks -> Audrey Hall local HTTP server -> Audrey Hall bubble state -> pet bubble UI`

Reason:

- No need to fork or deeply modify `claude-code`
- Fits the current Python/Tkinter `audrey_hall` app structure
- Easy to verify and extend later

## Implemented Files

### New files

- `audrey-hall/audrey_hall/hook_state.py`
  - Central Claude hook state machine
  - Tool-name to bubble mapping
  - Minimum dwell / delayed idle handling

- `audrey-hall/audrey_hall/hook_server.py`
  - Local HTTP server on `127.0.0.1:9527`
  - Receives Claude hook events
  - Exposes current state endpoint

- `audrey-hall/docs/claude-hooks.json`
  - Example Claude Code hook configuration

- `audrey-hall/docs/CLAUDE_INTEGRATION.md`
  - Human-readable integration notes

- `audrey-hall/docs/AI_HANDOFF.md`
  - This handoff document

### Updated files

- `audrey-hall/main.py`
  - Starts `ClaudeHookState`
  - Starts `ClaudeHookServer`
  - Listens for Claude state changes and applies them to all pets
  - Stops server on quit

- `audrey-hall/audrey_hall/pet.py`
  - Adds a bubble `Toplevel`
  - Shows/hides Claude status bubble beside the pet
  - Repositions bubble during visibility polling and dragging

- `audrey-hall/README.md`
  - Adds Claude integration entry points

## Runtime Architecture

```text
Claude Code
  -> Hook events
  -> http://127.0.0.1:9527/api/hook/*

audrey-hall/main.py
  -> ClaudeHookState
  -> ClaudeHookServer
  -> PetManager
  -> DesktopGif.set_claude_bubble()

Tkinter UI
  -> Bubble Toplevel beside pet
```

## HTTP API

Base:

- `127.0.0.1:9527`

Endpoints:

- `GET /api/heartbeat`
- `GET /api/current`
- `POST /api/hook/thinking`
- `POST /api/hook/working`
- `POST /api/hook/done`
- `POST /api/hook/permission`
- `POST /api/hook/idle`
- `POST /api/state`

## State Mapping

Hook/event to bubble mapping:

- `UserPromptSubmit` -> `正在组织回复...`
- `Read` / `Glob` / `Grep` / `LS` / `TaskGet` / `TaskList` / `ListMcpResourcesTool` -> `正在读取文件...`
- `Write` / `Edit` / `NotebookEdit` -> `正在构建...`
- `Bash` / `PowerShell` -> `正在执行命令...`
- `Agent` / `TaskCreate` / `TaskUpdate` / `Task` / `TodoWrite` / `TaskOutput` -> `正在分析...`
- `WebFetch` -> `正在获取网络内容...`
- `WebSearch` -> `正在搜索网络...`
- other tool -> `工作中...`
- `PostToolUse` -> `太棒了!`
- `PermissionRequest` -> `等待指示...`
- `Stop` / idle -> clear bubble

Internal state names currently used:

- `idle`
- `chatting`
- `working`
- `building`
- `analyzing`
- `fetching`
- `searching`
- `celebrating`
- `permission`

## Anti-Flicker Behavior

Implemented in `hook_state.py`:

- `ACTIVE_MIN_DURATION_MS = 1200`
- `DONE_DURATION_MS = 900`
- `IDLE_DELAY_MS = 300`

Behavior:

- Active Claude states are not immediately replaced by idle
- `done` shows briefly, then auto-transitions to idle
- Prevents rapid tool switches from flashing the bubble

## Claude Hook Config

Sample file:

- `audrey-hall/docs/claude-hooks.json`

Expected Claude hook flow:

- `SessionStart` -> start `audrey-hall`
- `UserPromptSubmit` -> `/api/hook/thinking`
- `PreToolUse` -> `/api/hook/working`
- `PostToolUse` -> `/api/hook/done`
- `PermissionRequest` -> `/api/hook/permission`
- `Stop` -> `/api/hook/idle`

Note:

- `SessionStart.command` contains a machine-specific path and may need adjustment if the environment changes

## Validation Performed

Completed checks:

- Python syntax compile:
  - `python -m compileall main.py audrey_hall`
- Isolated hook server smoke test:
  - `GET /api/heartbeat` returned success
- App runtime probe while `audrey-hall` was running:
  - `GET /api/current` returned current state
- Hook transition test:
  - `POST /api/hook/working` changed state to `building` for `Write`

## Current Limitations

- Bubble text is implemented; per-state GIF animation switching is not yet implemented
- Bubble style changes per state, but pet motion/animation still uses existing Audrey Hall logic
- Hook server has fixed loopback port `9527`
- No MCP tools yet
- Hook sample config currently assumes Windows and a local `.venv`

## Recommended Next Steps

Priority order:

1. Add Claude-state-driven animation switching in `audrey-hall/audrey_hall/pet.py`
2. Add a settings toggle for enabling/disabling Claude hook mode
3. Add tray/quick-menu status display for current Claude state
4. Optionally add MCP in phase 2 for user confirmations and input collection

## Important Context For Future AI Work

- This integration is intentionally decoupled from `claude-code` internals
- The preferred extension path is still external:
  - hooks first
  - MCP second
  - internal `claude-code` patching only if hook granularity becomes insufficient
- The current implementation should be treated as the stable base layer for future animation work

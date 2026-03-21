# Claude Code Crash/Freeze Bug Report — March 19-20, 2026 (RESOLVED)

## System
- macOS Big Sur 11.0.1 (unsupported — requires macOS 13+ for native installer)
- Node.js v18.20.8 via nvm
- npm install method (not native installer)
- Claude Code v2.1.42 (stable) — v2.1.79-2.1.80 broken on this system
- Model: Opus 4.6 (1M context), Claude Pro subscription

## RESOLUTION SUMMARY

Two root causes found and fixed after systematic debugging:

### Root Cause 1: 17 Hidden Plugin MCP Servers
Claude Code auto-installed marketplace plugins (`officialMarketplaceAutoInstalled: true`, `tengu_harbor: true`) that included **17 `.mcp.json` files** under `~/.claude/plugins/`. These tried to launch MCP servers via `bun` — a JavaScript runtime NOT installed on this system. On every startup, 17 child processes failed to spawn, leaving broken stdio pipes that destabilized Node.js's event loop. This caused crashes during ANY operation (Bash, Read, Edit, Grep — not just MCP calls).

**Fix:**
```bash
find ~/.claude/plugins -name ".mcp.json" -type f -delete
```

### Root Cause 2: Claude Code v2.1.79-2.1.80 Breaks MCP on Big Sur
Even after removing the hidden plugins, MCP tool calls crashed on v2.1.79/2.1.80. The same MCP servers work perfectly on v2.1.42 (confirmed on two computers). Downgrading to v2.1.42 resolved all MCP tool call freezes.

**Fix:**
```bash
# 1. Prevent auto-update
echo 'export CLAUDE_CODE_DISABLE_AUTO_UPDATE=1' >> ~/.zshrc
source ~/.zshrc

# 2. Clean install
npm uninstall -g @anthropic-ai/claude-code
npm install -g @anthropic-ai/claude-code@2.1.42

# 3. Make read-only to prevent auto-update from overwriting
chmod -R a-w ~/.nvm/versions/node/v18.20.8/lib/node_modules/@anthropic-ai/claude-code/

# Result: "Auto-update failed" message on startup — this is correct behavior
```

**Note:** `CLAUDE_CODE_DISABLE_AUTO_UPDATE=1` alone does NOT prevent auto-updates. The `chmod -R a-w` is required to actually block the update mechanism.

### Additional Fixes Applied
- **Native installer leftovers deleted:** `rm -rf ~/Library/Application Support/Claude/claude-code*`
- **Quarantine xattrs cleared:** `xattr -cr ~/.claude/ && xattr -cr ~/.claude.json`
- **print() to stdout fixed** in total-reaper-mcp: `tool_registry.py:170` and `dsl/tools.py:536` redirected to stderr
- **ENABLE_TOOL_SEARCH=false** set in `~/.claude/settings.json` env vars

## Bug Description

### Two Crash Types Observed
1. **"Interrupted" crash** — session dies mid-operation, shows "Interrupted · What should Claude do instead?" — caused by broken MCP child processes corrupting Node.js event loop
2. **"tcp.connection waiting" freeze** — Claude appears stuck, command line is free but no response — caused by MCP tool call timeout in v2.1.79-2.1.80

### What Crashed
- With MCP servers configured — tool calls hang indefinitely, then crash
- Without MCP servers configured — also crashes, due to 17 hidden plugin MCP servers
- During file reads, tool calls, web searches, and parallel operations
- On both computers after auth outage on March 18-19

## Timeline
1. **March 18, 01:35** — Auth failure: "Invalid authentication credentials" (Anthropic-side outage)
2. **March 18, 01:37** — "Authorization failed - Internal server error" on login page
3. **March 18-19** — After auth resolved, Claude Code auto-updated to 2.1.79 and began crashing
4. **March 19** — Further auto-updated to 2.1.80
5. **March 19-20** — Systematic debugging: identified hidden plugins + version regression
6. **March 20** — Fixed: deleted plugin .mcp.json files + downgraded to 2.1.42 + chmod read-only

## Detailed Investigation Log

### 1. Native installer conflict (FIXED)
- Dead native binary v2.1.22 at `~/Library/Application Support/Claude/claude-code/`
- 180MB Mach-O x86_64 binary from Feb 8 — incompatible with Big Sur
- **Fix:** Deleted directories

### 2. Orphaned MCP processes (FIXED)
- `reaper_reapy_mcp` configured in `~/.claude.json` under `projects./Users/noagorelik.mcpServers`
- Auto-launched without Reaper running → hung indefinitely
- **Fix:** Removed from config, killed processes

### 3. Hidden marketplace plugin MCP servers (ROOT CAUSE #1 — FIXED)
- `officialMarketplaceAutoInstalled: true` caused auto-download of plugins
- `tengu_harbor: true` + `tengu_harbor_ledger` enabled the plugin system
- 17 `.mcp.json` files found across `external_plugins/` and `plugins/` directories:
  - discord, telegram, fakechat (harbor_ledger plugins)
  - asana, context7, firebase, github, gitlab, greptile, laravel-boost, linear, playwright, serena, slack, stripe, supabase, example-plugin
- All tried to launch via `bun` command (not installed, exit 127)
- Broken child processes destabilized ALL Claude Code operations
- **Key insight:** Working computer #2 does NOT have `external_plugins/` directory
- **Fix:** `find ~/.claude/plugins -name ".mcp.json" -type f -delete`
- **Risk:** Server-side flags may recreate files on future updates. Monitor with same find command.

### 4. MCP tool call regression in v2.1.79-2.1.80 (ROOT CAUSE #2 — FIXED)
- Both `reaper-reapy-mcp` and `total-reaper-mcp` freeze on tool calls in v2.1.79/2.1.80
- MCP servers respond correctly (confirmed via direct Python testing and REAPER console)
- Python server returns valid JSON via stdio when tested manually from terminal
- But Claude Code v2.1.79-2.1.80 freezes when making the same tool call
- Same MCP servers work perfectly on v2.1.42 (both computers)
- **Fix:** Downgrade to v2.1.42 + chmod read-only to prevent auto-update

### 5. Version downgrade challenges
- `tengu_bridge_min_version: 2.1.70` exists in server-side config but does NOT prevent 2.1.42 from running
- `CLAUDE_CODE_DISABLE_AUTO_UPDATE=1` env var alone does NOT prevent auto-update
- Auto-update overwrites npm package on every startup within seconds
- **Fix:** `chmod -R a-w` on the npm package directory → auto-update fails gracefully with "Auto-update failed" message

### 6. MCP Tool Search / lazy loading (DISABLED)
- `tengu_mcp_tool_search: true` — server-side, can't disable permanently
- Known bug in v2.1.69 where `defer_loading + cache_control` broke ALL MCP calls
- Disabled via `ENABLE_TOOL_SEARCH=false` in `~/.claude/settings.json` env
- May not be necessary on v2.1.42 but kept as safety measure

### 7. Sentry cloud MCP connector
- `claudeAiMcpEverConnected: ["claude.ai Sentry"]` — restored by server on every startup
- `tengu_claudeai_mcp_connectors: true` — can't disable permanently
- May cause network timeouts but not confirmed as crash source
- Less of an issue on v2.1.42

### 8. print() to stdout corruption (FIXED)
- `total-reaper-mcp/server/tool_registry.py:170` printed to stdout during startup
- Corrupts MCP JSON-RPC stream
- **Fix:** Redirected to stderr with `file=sys.stderr`
- Also fixed `server/dsl/tools.py:536`

### 9. Quarantine xattrs (FIXED)
- macOS quarantine flags on `~/.claude/` files
- Previously caused settings persistence issues (couldn't save config)
- **Fix:** `xattr -cr ~/.claude/ && xattr -cr ~/.claude.json`

## Server-Side Feature Flags (cannot be permanently changed)
These `tengu_*` flags in `cachedGrowthBookFeatures` are downloaded from Anthropic's servers on every startup and overwrite local changes:
- `tengu_harbor: true` — enables plugin system
- `tengu_harbor_ledger` — lists discord/telegram/fakechat
- `tengu_claudeai_mcp_connectors: true` — enables cloud MCP connectors
- `tengu_mcp_tool_search: true` — enables Tool Search / lazy loading
- `tengu_bridge_min_version: 2.1.70` — minimum version (not enforced on 2.1.42)
- `tengu_pid_based_version_locking: true` — version locking mechanism

## MCP Config Architecture
- `~/.claude.json` → WHERE MCP servers actually live (user + per-project scope)
- `~/.claude/settings.json` → permissions, model, env vars — NOT for MCP definitions
- `.mcp.json` → team-shared MCP (project root) — also used by plugins (crash source!)
- `claude_desktop_config.json` → Claude Desktop (GUI app), NOT Claude Code
- Many third-party guides incorrectly say to use `settings.json` for MCP — this is wrong

## Reproduction Steps (for GitHub issue)
1. macOS Big Sur 11.0.1, Node 18.20.8, npm install of Claude Code
2. Allow Claude Code to auto-update to v2.1.79 or later
3. Claude Code auto-installs marketplace plugins with .mcp.json files referencing `bun`
4. On every startup, 17 MCP child processes fail → broken stdio pipes → Node.js event loop corruption
5. ANY tool call (Bash, Read, Edit, MCP) can trigger crash
6. Additionally, MCP tool calls specifically freeze/hang on v2.1.79-2.1.80 (regression)
7. Same MCP servers work perfectly on v2.1.42

## Fix Summary
```bash
# 1. Delete hidden plugin MCP configs
find ~/.claude/plugins -name ".mcp.json" -type f -delete

# 2. Clear quarantine xattrs
xattr -cr ~/.claude/ && xattr -cr ~/.claude.json

# 3. Delete native installer leftovers (Big Sur)
rm -rf ~/Library/Application\ Support/Claude/claude-code
rm -rf ~/Library/Application\ Support/Claude/claude-code-vm

# 4. Set auto-update disable (necessary but not sufficient alone)
echo 'export CLAUDE_CODE_DISABLE_AUTO_UPDATE=1' >> ~/.zshrc
source ~/.zshrc

# 5. Install stable version
npm uninstall -g @anthropic-ai/claude-code
npm install -g @anthropic-ai/claude-code@2.1.42

# 6. Lock version with read-only permissions (prevents auto-update)
chmod -R a-w ~/.nvm/versions/node/v18.20.8/lib/node_modules/@anthropic-ai/claude-code/

# 7. Optional: disable Tool Search
# Add to ~/.claude/settings.json:
# "env": { "ENABLE_TOOL_SEARCH": "false" }
```

## Files Referenced
- `~/.claude.json` — main config (MCP servers, project settings, feature flags)
- `~/.claude/settings.json` — global settings (ENABLE_TOOL_SEARCH env)
- `~/.claude/settings.local.json` — local permissions
- `~/.claude/plugins/` — marketplace plugins (root cause #1 location)
- `~/total-reaper-mcp/` — total-reaper MCP server
- `~/total-reaper-mcp/server/tool_registry.py` — fixed print() corruption
- `~/total-reaper-mcp/server/dsl/tools.py` — fixed print() corruption
- `~/Library/Application Support/REAPER/Scripts/mcp_bridge_file_v2.lua` — Lua bridge

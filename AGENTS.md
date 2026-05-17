<EXTREMELY_IMPORTANT>

## EXECUTE FIRST - REQUIRED SESSION LOAD

BEFORE responding to the first user message in this session, you MUST execute
these two file reads in order:

1. Read `/Users/macbook/Knowledge/brain.md`
2. Read `/Users/macbook/Knowledge/reascripts/index.md`

This is not optional and not "load if relevant". Read both files FIRST, then
answer. In your response, briefly confirm in one sentence that you read both,
naming one specific fact from each file that proves you read it.

After this initial load, follow the lazy-load protocol in
`/Users/macbook/Knowledge/CLAUDE.md`: when a trigger keyword from
`reascripts/index.md` appears in conversation, read the corresponding
topic file.

</EXTREMELY_IMPORTANT>

# ReaScripts

This project contains REAPER automation work: Lua and Python ReaScripts,
JSFX plugins, audio-processing tools, and MCP/REAPER integration.

Root `AGENTS.md` is the Codex project head. `CLAUDE.md` may contain fuller
Claude-specific context, but files under `.claude/agents/` are auxiliary role
definitions and must not be treated as the project head.

## Knowledge Base

When working on a task, check `/Users/macbook/Knowledge/reascripts/index.md`
for relevant context files.
Load topic files only when the current task matches a listed topic.
Never load files from other sections unless explicitly asked.
`/Users/macbook/Knowledge/brain.md` — load on demand for cross-project context, machine map, or strategic decisions.
Cross-project files (_infrastructure/, _agents/, _shared/) may be loaded when
relevant.

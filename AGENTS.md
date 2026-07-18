# AGENTS.md

## Project Goal

Build a local-first Obsidian knowledge base for summarizing frontier technical materials, extracting idea suggestions, and generating weekly/monthly todo suggestions.

## Hard Rules

- Markdown files are the primary data layer.
- Do not silently overwrite user-authored notes.
- AI-generated ideas and todos must go into suggestion files first.
- Only user-accepted suggestions may be moved into formal idea lists or weekly/monthly todo files.
- MVP must not require external LLM APIs.
- MVP must support manually pasted text in Inbox.

## MVP Commands

- Initialize vault structure: `python scripts/kb.py init`
- Parse inbox: `python scripts/kb.py ingest`
- Generate manual LLM prompts: `python scripts/kb.py make-prompts`
- Move accepted ideas: `python scripts/kb.py accept-ideas`
- Move accepted todos: `python scripts/kb.py accept-todos`
- Show status: `python scripts/kb.py status`

## Completion Criteria

A task is complete only if:

1. It preserves existing user content.
2. It creates readable Markdown output.
3. It updates status fields consistently.
4. It includes a short usage note.
5. It has been tested with at least one sample Inbox item.

## Current Phase Status

- Phase 0 (init): **done**
- Phase 1 (ingest parser): **done**
- Phase 2 (make-prompts): pending
- Phase 3 (manual output import): pending
- Phase 4 (accept-ideas / accept-todos): pending
- Phase 5 (status dashboard): **done** (basic version)

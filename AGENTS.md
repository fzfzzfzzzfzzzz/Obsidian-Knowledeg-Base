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
- **Git: commit and push only when the user explicitly asks.** Never push proactively. It is fine to stage/commit locally to keep work organized, but `git push` (and any remote-changing action) requires an explicit user command.
- **Offline-first: all frontend assets (JS libs, fonts, icons) must be self-hosted under `scripts/web/static/`.** Never depend on an external CDN — the workbench must render fully when offline. The Lucide icon library is vendored at `scripts/web/static/lucide.min.js`; reference it as `/static/lucide.min.js?v=N` (bump `v=` on every content change to bust browser cache).

## Frontend / Icon Conventions (learned from v0.4.16 incident)

This project uses **Lucide** (local, vendored) for all icons. To avoid repeating the multi-hour debugging saga of v0.4.16, follow these rules:

### Icon usage
- Render icons as `<i data-lucide="icon-name"></i>`. `createIcons()` internally converts kebab-case → PascalCase, so `data-lucide="alarm-clock"` matches `icons.AlarmClock` automatically — **do not** build manual name-mapping layers.
- `base.html` defines a global `window.refreshIcons()` that calls `createIcons()`, plus a `MutationObserver` that re-runs it on DOM changes. **Always call `window.refreshIcons()` after any JS-generated HTML** that contains `<i data-lucide>`.
- Icon size/alignment is handled by the `svg.lucide` CSS rule in `style.css`. Don't scatter ad-hoc `width/height` overrides per component.

### When icons (or any rendered UI element) don't show up
**Do not** burn rounds on static analysis or node simulations. Node ≠ browser. Follow this order:
1. **Ask for the F12 Console output FIRST.** "UI 不显示" = open DevTools, copy Console, paste it. One screenshot/line of console output is worth 5 rounds of guessing. Add a one-line `console.log` to the suspect function if needed.
2. **Add a visible marker to isolate the failure mode.** A temporary `outline: 1px solid red` on the element distinguishes "not in DOM" (nothing shows) from "in DOM but invisible" (red box shows). This single trick would have saved hours in v0.4.16.
3. **Only then** dig into code. The two failure modes have completely different fixes (registration/timing vs. CSS/color/size).

### Vendoring a JS library
- After downloading any vendored JS, **verify the content before committing**: check file size is plausible for a full bundle, and grep for a few specific symbol names you'll use. The v0.4.16 bug was a truncated/partial bundle that silently lacked most icons.
- Pin a specific version in the download URL (`@0.460.0`, not `@latest`) so the vendored file is reproducible.

## Commands

MVP(本地无 LLM 也能跑):
- Initialize vault structure: `python scripts/kb.py init`
- Parse inbox: `python scripts/kb.py ingest`
- Generate manual LLM prompts: `python scripts/kb.py make-prompts`
- Move accepted ideas: `python scripts/kb.py accept-ideas`
- Move accepted todos: `python scripts/kb.py accept-todos`
- Show status: `python scripts/kb.py status`

Additional commands(require LLM / web deps, gracefully degrade when absent):
- Test LLM connectivity: `python scripts/kb.py llm-test`
- Auto-generate summary via LLM: `python scripts/kb.py make-prompts --auto`
- Backfill `summary_path` from existing summaries: `python scripts/kb.py make-prompts --reconcile`
- Extract idea/todo suggestions from summaries: `python scripts/kb.py extract-suggestions`
- Clean X (Twitter) source body noise: `python scripts/kb.py clean-x`
- Start FastAPI reading frontend: `python scripts/kb.py serve`

## Completion Criteria

A task is complete only if:

1. It preserves existing user content.
2. It creates readable Markdown output.
3. It updates status fields consistently.
4. It includes a short usage note.
5. It has been tested with at least one sample Inbox item.

## Current Phase Status

- Phase 0 (init): **done**
- Phase 1 (ingest parser): **done** (free-form text + KB_ITEM dual format, optional LLM)
- Phase 2 (make-prompts): **done** (manual / `--auto` / `--reconcile` modes)
- Phase 3 (manual output import): **done** (LLM auto-write + manual paste paths)
- Phase 4 (accept-ideas / accept-todos): **done**
- Phase 5 (status dashboard): **done** (CLI `status` + FastAPI web UI)

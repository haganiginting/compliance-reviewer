# AI Architecture Compliance Reviewer - Agent Operating Guide

This repo is a personal, local-only AI Architecture Compliance Reviewer for a beginner developer on macOS. Future agents must treat this file as the concise operating guide and `BUILD_PROMPTS.md` as the detailed build roadmap and progress source of truth.

## Required Reading Order

1. Read `AGENTS.md` first.
2. Read `BUILD_PROMPTS.md` before changing code or continuing any phase.
3. Confirm the current sub-phase from `BUILD_PROMPTS.md`, then work on exactly one sub-phase at a time.

Do not jump ahead, combine sub-phases, or begin the next sub-phase after finishing the current one. At the end of every sub-phase, stop and produce the required Handoff Report.

## Current Project State

Sub-Phase 1.1 is complete. Unless `BUILD_PROMPTS.md` has a newer project-state note, the next implementation work starts at Sub-Phase 1.2 - PDF Parsing Pipeline.

After each completed sub-phase, update the relevant project-state note in `BUILD_PROMPTS.md`. Keep this file stable unless the operating rules or project-level conventions change.

## Project Boundaries

- This is a personal, local-only project.
- Do not add authentication, billing, Docker, or cloud deployment unless the human explicitly asks for it.
- Prefer local and free components, including ChromaDB, local embeddings, and SQLite.
- Keep the Anthropic model name in one config constant and use a cost-effective model during development.
- Build for a beginner user: explain manual terminal steps plainly in every Handoff Report.

## Human And Agent Responsibilities

The agent performs all file creation, code writing, and repo-local edits.

The human performs anything that requires local/private action outside repo editing, including:

- Installing system tools.
- Running servers when requested.
- Sorting private agency PDFs.
- Pasting API keys into local env files.
- Clicking through browser checks.
- Making Git commits.

Never assume the human knows virtual environments, Node, npm, CORS, Git, or API keys. Explain what each command does and why when asking them to run it.

## Safety Rules

- Never print secrets.
- Never commit `.env`.
- Never commit private PDFs.
- Never commit generated Chroma data or SQLite databases.
- Never commit `node_modules/`, `.next/`, virtualenvs, `__pycache__/`, or `*.pyc`.
- Whenever new runtime/generated files are introduced, confirm `.gitignore` covers them.
- Treat `backend/data/source_pdfs/` as private user data storage.

## Repo Conventions

- Backend: FastAPI Python app in `backend/`.
- Frontend: Next.js + TypeScript app in `frontend/`.
- Generated and private backend data belongs under `backend/data/`.
- Agency PDF folders use lowercase agency codes: `bca`, `scdf`, `ura`, `lta`, `nparks`, `nea`, `pub`.
- `BUILD_PROMPTS.md` owns the phase details, acceptance criteria, and progress notes.

## Handoff Report Format

At the end of every sub-phase, stop and output exactly these four sections:

1. **What I changed** - a short summary of files created/edited and what they do.
2. **Manual steps for you (the human)** - the exact commands or actions the human must perform, each with a beginner-friendly explanation of what it does and why. Cover anything you cannot do yourself: tool installation, starting servers, moving PDFs, setting the API key, browser actions.
3. **Verification checklist** - concrete checks the human (with your help) should confirm to prove this sub-phase works. State what "good output" looks like.
4. **Prerequisites before the next sub-phase** - what must be true/confirmed before you proceed, and the name of the next sub-phase.

Then wait for the human to confirm before continuing.

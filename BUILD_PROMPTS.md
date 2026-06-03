# AI Architecture Compliance Reviewer — Agent Build Instructions

> **Agent: read this header before doing anything.**
>
> You are an agentic coding assistant building a project for a **beginner** developer on **macOS**. This document is your complete build specification. The human will reference this whole file to you across sessions — they will NOT copy-paste individual sections. You are responsible for tracking progress and knowing which sub-phase comes next.
>
> **Your operating rules for the entire project:**
> 1. Build **one sub-phase at a time, in order.** Do not jump ahead or combine sub-phases.
> 2. After finishing each sub-phase, **STOP** and produce a **Handoff Report** (format defined below). Do not begin the next sub-phase until the human confirms the manual steps are done and verification passed.
> 3. The human is a **beginner** with terminals and tooling. In every Handoff Report, spell out the manual steps they must run themselves, explain in plain language what each command does and why, and never assume prior knowledge of virtual environments, Node, npm, CORS, Git, etc.
> 4. **You** perform all file creation and code writing. The **human** performs anything you cannot do from inside the repo: installing system tools, running servers, sorting their private PDFs, pasting API keys, clicking in the browser, and `git commit`.
> 5. This is a **personal, local-only** project. Never add authentication, billing, Docker, or cloud deployment unless explicitly told to.
> 6. Prefer **local, free** components (ChromaDB, local embeddings, SQLite) over paid cloud services. Keep the Anthropic model name in a single config constant and use a cheaper model during development.
> 7. Never print secrets. Never commit `.env`. Whenever you generate new runtime files, confirm `.gitignore` covers them.
>
> **Environment facts:** macOS · single monorepo · the human already has the agency code PDFs downloaded and will sort them into folders when you tell them where.

---

## The Handoff Report (produce this at the end of EVERY sub-phase)

When you finish a sub-phase, stop and output exactly these four sections:

1. **What I changed** — a short summary of files created/edited and what they do.
2. **Manual steps for you (the human)** — the exact commands or actions the human must perform, each with a beginner-friendly explanation of what it does and why. Cover anything you cannot do yourself: tool installation, starting servers, moving PDFs, setting the API key, browser actions.
3. **Verification checklist** — concrete checks the human (with your help) should confirm to prove this sub-phase works. State what "good output" looks like.
4. **Prerequisites before the next sub-phase** — what must be true/confirmed before you proceed, and the name of the next sub-phase.

Then wait for the human to confirm before continuing.

---

## Recommended Repository Structure (create this in Sub-Phase 1.1)

Use a **monorepo** — one folder, one Git repo, holding both frontend and backend. For a solo personal project this is simpler than two repos: one place to clone, one to back up, and the two halves never drift out of sync.

```
compliance-reviewer/
├── README.md
├── .gitignore
├── .env.example                # template for secrets (committed)
├── .env                        # real secrets (NEVER committed)
├── docs/
│   └── roadmap.html            # the roadmap, for reference
│
├── backend/                    # Python + FastAPI
│   ├── requirements.txt
│   ├── main.py                 # FastAPI app entry point
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py           # env vars, agency definitions, model constant
│   │   ├── pdf/                # PDF parsing (PyMuPDF)
│   │   ├── rag/                # ingestion + retrieval (LlamaIndex + ChromaDB)
│   │   ├── review/             # compliance prompt + Claude calls
│   │   ├── storage/            # SQLite models + queries
│   │   └── api/                # FastAPI route handlers
│   ├── scripts/
│   │   └── ingest.py           # CLI to build the knowledge base
│   └── data/
│       ├── source_pdfs/        # the human's downloaded agency PDFs
│       │   ├── bca/  scdf/  ura/  lta/  nparks/  nea/  pub/  ica/
│       ├── chroma/             # local vector DB (auto-generated)
│       └── app.db              # SQLite database (auto-generated)
│
└── frontend/                   # Next.js + TypeScript
    ├── package.json
    └── src/
        ├── app/                # Next.js App Router pages
        ├── components/
        └── lib/                # API client, types
```

`data/` lives inside `backend/` because the Python code reads/writes it. The `chroma/`, `app.db`, and the PDFs are all git-ignored (large and/or private).

---

# PHASE 1 — Core Engine (BCA, SCDF & URA)

**Goal:** a terminal command that takes a drawing PDF and returns a JSON compliance report tagged by the three core agencies. Split into 4 sub-phases.

---

## Sub-Phase 1.1 — Project Scaffold & Tooling

Set up a brand-new monorepo from scratch (no repo exists yet) named `compliance-reviewer`, matching the structure above.

**Backend:**
- `requirements.txt` with: `fastapi`, `uvicorn[standard]`, `python-dotenv`, `pydantic`, `pymupdf`, `llama-index`, `chromadb`, `anthropic`, `llama-index-vector-stores-chroma`, `llama-index-embeddings-huggingface`.
- `main.py`: a minimal FastAPI app exposing `GET /health` → `{"status": "ok"}`.
- `app/config.py`: loads env vars from the root `.env` via python-dotenv; defines the 8 agencies (BCA, SCDF, URA, LTA, NParks, NEA, PUB, ICA) each with a short description and a `core` boolean (True for BCA/SCDF/URA); defines a single `CLAUDE_MODEL` constant (use a cost-effective model for development).
- Create the full empty package structure (`app/pdf/`, `app/rag/`, `app/review/`, `app/storage/`, `app/api/`, `scripts/`, and the eight `data/source_pdfs/<agency>/` folders), each Python package with an `__init__.py`.

**Frontend:**
- Scaffold a minimal Next.js 14 + TypeScript app (App Router) with Tailwind CSS.
- A single home page that says "Compliance Reviewer" and fetches `GET http://localhost:8000/health`, displaying the status.

**Root:**
- `.gitignore` ignoring: `.env`, `__pycache__/`, `*.pyc`, `.venv/`, `node_modules/`, `.next/`, `backend/data/chroma/`, `backend/data/app.db`, `backend/data/source_pdfs/**/*.pdf`.
- `.env.example` containing `ANTHROPIC_API_KEY=your_key_here`.
- `README.md` with a short description and an empty "Getting Started" section.

Do not run install commands yourself — create files only. In your Handoff Report, walk the human through: opening Terminal, `cd`-ing to their home folder, `git init`, creating and activating a Python virtual environment (`python3 -m venv .venv`, `source .venv/bin/activate`), `pip install -r requirements.txt`, `npm install` in frontend, copying `.env.example` to `.env`, and starting both servers. Explain each command. Verification should confirm `/health` returns ok, the frontend home page shows "ok", and `.env` is not staged by Git.

> **Project state note after Sub-Phase 1.1 (2026-06-04):**
> Sub-Phase 1.1 has been implemented, the initial scaffold has been committed locally, and a private remote GitHub repository has been created and connected as the project remote. Continue future work from Sub-Phase 1.2 onward using this local repo plus GitHub remote backup/sync. Keep `.env`, private PDFs, generated Chroma data, and SQLite databases out of Git.

---

## Sub-Phase 1.2 — PDF Parsing Pipeline

Implement PDF parsing in `backend/app/pdf/`.

- Take a path to a multi-page PDF drawing.
- Use PyMuPDF (`fitz`) to extract per page: raw text, text annotations/labels, and a rendered PNG at ~150 DPI (justify this DPI in a comment — readable for Claude vision without bloating tokens).
- Return Pydantic models: `document` (filename, page_count) and `pages` (list of `{page_number, text, annotations, image_base64}`).
- Save rendered images to a temp working dir and also provide them base64-encoded for later vision input.
- Add a CLI: `python -m app.pdf.parse <path-to-pdf>` that prints a summary (page count, characters per page, image-rendered confirmation) WITHOUT dumping base64.

In your Handoff Report, tell the human to place a sample PDF, activate the venv, and run the CLI. Verification: correct page count, non-zero text per page (or a clear explanation of how image-only scans degrade gracefully), a PNG appears, no base64 floods the terminal.

---

## Sub-Phase 1.3 — Knowledge Base Ingestion (BCA, SCDF, URA)

Implement the RAG ingestion pipeline in `backend/app/rag/` and a CLI at `backend/scripts/ingest.py`.

- Use LlamaIndex with ChromaDB as a LOCAL persistent store at `backend/data/chroma/`.
- Use a local HuggingFace embedding model (e.g. `BAAI/bge-small-en-v1.5`) so embeddings are free and offline — explain this in a comment.
- One ChromaDB collection per agency (`sg_bca`, `sg_scdf`, `sg_ura`), with the function generic enough that `sg_lta`, `sg_nparks`, etc. work later just by dropping PDFs in the right folder.
- The ingest script scans `backend/data/source_pdfs/<agency>/`, chunks PDFs by logical section (reasonable size + overlap — explain the values), attaches metadata (`agency`, `source_filename`, `page_number`), and upserts into that agency's collection.
- Support a `--reset` flag (clear a collection before re-ingest) and an `--agency` flag (ingest one agency).
- Print a per-agency summary: PDFs found, chunks created, embedded.
- Provide a small retrieval sanity-check function/script: given a query + agency, return the top 3 chunks with source filename and page.

In your Handoff Report, instruct the human to: create their Anthropic API key and paste it into the root `.env` (explain `.env` is git-ignored), sort their BCA/SCDF/URA PDFs into the matching lowercase folders, run ingestion per agency, and warn them the first run downloads the embedding model (one-time, a few hundred MB). Verification: `chroma/` is non-empty, non-zero chunk counts per agency, the sanity check returns 3 relevant chunks with correct metadata, `--reset` doesn't duplicate.

---

## Sub-Phase 1.4 — Compliance Review Engine (Phase 1 milestone)

Implement the review engine in `backend/app/review/` tying PDF parsing + RAG + Claude together.

- Input: a drawing PDF path.
- Pipeline: parse the PDF; for each core agency (BCA, SCDF, URA) build a retrieval query from the drawing text/labels and retrieve the most relevant clauses from that agency's collection; call the Claude API (model from the config constant) with retrieved clauses + page text + page images (vision); run the three agency reviews concurrently with `asyncio` (explain the concurrency in comments).
- Output one structured JSON report:
  ```
  {
    "document": {...},
    "reviewed_at": iso8601,
    "agencies": [
      { "agency": "BCA",
        "issues": [
          { "title", "severity": "Critical|Major|Advisory",
            "description", "clause_reference", "drawing_location",
            "suggested_resolution" } ] }, ...
    ],
    "summary": { "total_issues", "by_agency", "by_severity" }
  }
  ```
- Strong system prompt (in its own editable file) instructing Claude to flag ONLY issues supported by retrieved clauses, cite the clause reference, and never invent clause numbers.
- Validate Claude's output with Pydantic; on failure, retry once with a corrective instruction.
- CLI: `python -m app.review.run <path-to-pdf>` prints the JSON and writes it to a file.

In your Handoff Report, confirm the human has a valid `ANTHROPIC_API_KEY` (this sub-phase spends real money — give a rough per-run cost), tell them how to run it on a real drawing, and tell them to spot-check 2–3 cited clauses against their source PDFs. Verification: valid JSON matching the schema, issues tagged by correct agency, each issue has clause reference + severity + resolution, concurrency visible in timing/logs, cited clauses are real. **Then instruct the human to make the Phase 1 Git commit** (explain `git add .` and `git commit -m "..."` in plain language). State the Phase 2 prerequisite: remaining agency PDFs (LTA, NParks, NEA, PUB) ready to sort.

---

# PHASE 2 — Full Coverage + Web UI

**Goal:** upload a PDF in the browser, get a full 7-agency report, filterable and exportable. Split into 5 sub-phases.

---

## Sub-Phase 2.1 — Ingest Remaining 4 Agencies

Extend the knowledge base from 3 to 7 agencies (the ingest code is already generic).

- Confirm ingestion handles `lta`, `nparks`, `nea`, `pub` → collections `sg_lta`, `sg_nparks`, `sg_nea`, `sg_pub`.
- Update `app/review` to loop over a CONFIGURABLE active-agency list (default: the 7 non-ICA agencies) instead of the hardcoded 3. Keep ICA excluded for now.
- Drive the active-agency list from `app/config.py` so agencies can be toggled in one place.
- Update the JSON report + summary to cover all 7.

Handoff Report: tell the human to sort the 4 new agency PDF sets into their folders, run ingestion per agency, and re-run a CLI review. Verification: all 7 collections non-empty, a CLI review returns up to 7 agencies, toggling an agency off in config removes it next run.

---

## Sub-Phase 2.2 — Backend API + SQLite Storage

Expose the review engine over HTTP via FastAPI in `backend/app/api/`, and build SQLite storage in `backend/app/storage/`.

- `POST /api/reviews` — accepts a multipart PDF upload, starts a review as a background task, returns a `review_id` immediately (do not block for minutes).
- `GET /api/reviews/{review_id}` — returns status (`processing|done|error`) and, when done, the full report.
- `GET /api/reviews` — lists past reviews (id, filename, created_at, total_issues, status).
- Implement SQLite (SQLModel or plain sqlite3 — pick one and explain) with `reviews` and `issues` tables; persist every completed report.
- Enable CORS for `localhost:3000` (explain what CORS is in a comment).

Handoff Report: tell the human how to start the backend and test each endpoint with `curl`, including uploading a PDF via `curl -F` (explain `-F` and `@`). Verification: upload returns a `review_id` fast, polling reaches `done` with the full report, `app.db` exists and the review survives a server restart, the list endpoint shows it.

---

## Sub-Phase 2.3 — Upload UI & Project Dashboard

Build the upload + dashboard UI in `frontend/` with Next.js App Router + Tailwind.

- Dashboard page: drag-and-drop PDF upload zone + project type selector (Residential / Commercial / Industrial / Mixed) + a list of past reviews from `GET /api/reviews` (filename, date, total issues, status badge).
- On upload: `POST /api/reviews`, then show a processing state that polls `GET /api/reviews/{id}` every few seconds until done, then routes to the report page.
- A typed API client in `src/lib/`.
- Clean, professional, neutral styling. No auth, no login.
- Use `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`) for the API URL.

Handoff Report: tell the human to create `frontend/.env.local` with `NEXT_PUBLIC_API_BASE` (explain what `.env.local` is), run both servers, and drag in a PDF. Verification: upload works and shows a processing state, finishing navigates onward, the dashboard lists past reviews.

---

## Sub-Phase 2.4 — Compliance Report View, Filtering & Notes

Build the report view in `frontend/` on `/reviews/[id]`.

- Fetch the full report from `GET /api/reviews/{id}`.
- Summary bar: total issues, counts per agency (colour-coded per the roadmap palette), counts per severity.
- Issues grouped by agency, colour-coded; each issue card shows title, severity tag, description, clause reference, drawing location, and an expandable "Suggested Resolution".
- Agency filter chips and severity filter to show/hide issues.
- Per-issue personal notes saved to the backend: add `PATCH /api/issues/{id}/note` and a `note` column on the issues table.

Handoff Report: tell the human to restart the backend (new routes), open a finished review, exercise filters, add a note, and reload to confirm it persisted. Verification: grouped colour-coded issues + working summary bar, filters work, a note survives reload.

---

## Sub-Phase 2.5 — PDF Report Export (Phase 2 milestone)

Add one-click PDF export.

- Backend-generated for consistency: `GET /api/reviews/{id}/export.pdf` rendering a clean report (filename + date, summary table, then a section per agency listing issues with severity, clause reference, description, resolution, and any personal note). Use reportlab or weasyprint — pick one and explain the tradeoff.
- An "Export PDF" button on the report page that downloads it.

Handoff Report: tell the human to restart the backend, click Export PDF, and open the file. Verification: PDF opens and is readable with summary + per-agency sections, notes appear, severities/clauses render. **Then instruct the human to make the Phase 2 Git commit.** State the Phase 3 prerequisite: decide whether ICA is needed (only for airport/terminal/checkpoint projects).

---

# PHASE 3 — Polish, Tune & ICA Extension

**Goal:** accurate and smooth enough for a real project; ICA available on demand. Split into 4 sub-phases.

---

## Sub-Phase 3.1 — Prompt & Retrieval Tuning

Improve accuracy, no new features.

- Add a lightweight eval harness: a folder of sample drawings + a YAML/JSON file of "expected findings"; a script runs reviews and reports caught/missed findings.
- Make retrieval parameters (chunk size, overlap, `top_k` per agency) configurable in `config.py`.
- Allow per-agency system-prompt overrides (especially URA development-control parameters and PUB drainage/MPL, which are number-heavy); keep prompts in editable files.
- Add structured logging of each agency's retrieved chunks per review so the human can see WHY Claude flagged something.

Handoff Report: tell the human to add 1–3 drawings they know the answers for, fill in the expected-findings file, and run the harness. Verification: harness reports caught/missed, changing `top_k`/chunk size measurably changes retrieval, logs show the clauses behind each flag.

---

## Sub-Phase 3.2 — Inline PDF Viewer

Add an inline viewer on the report page.

- Serve the original PDF from the backend: `GET /api/reviews/{id}/file`.
- Embed a viewer (react-pdf or pdf.js) in a split-pane layout: report one side, drawing the other.
- Clicking an issue with a drawing_location/page jumps the viewer to that page.
- Explain any new dependency.

Handoff Report: tell the human to restart both servers, open a report, and click an issue. Verification: the drawing renders in the split pane, clicking an issue navigates to the cited page.

---

## Sub-Phase 3.3 — ICA Module (Conditional)

Add ICA as an OPTIONAL 8th agency, active only for infrastructure projects.

- Add `sg_ica` ingestion support (same generic pipeline; PDFs in `data/source_pdfs/ica/`).
- Add a project-type concept: when the user selects "Infrastructure (airport / terminal / checkpoint)" at upload, ICA is included; otherwise excluded.
- Surface ICA issues in report and export, colour-coded.
- Handle gracefully an empty ICA collection (some ICA standards aren't public): show a clear "ICA knowledge base not loaded" notice instead of failing.

Handoff Report: tell the human (if they have ICA PDFs) to place them and ingest, then upload with project type "Infrastructure". Verification: Infrastructure includes ICA, other types exclude it, empty ICA collection shows a notice rather than crashing.

---

## Sub-Phase 3.4 — Cross-Agency Conflict Detection (final milestone)

Add conflict detection as the final polish.

- After all agency reviews complete, run an additional Claude pass over the combined issue list to identify cases where two agencies impose conflicting requirements on the SAME element (e.g. BCA setback vs PUB drainage reserve; LTA road reserve vs URA setback).
- Output a `conflicts` array: `{ element, agencies_involved, description, recommended_action: "seek authority pre-consultation" }`.
- Show conflicts in a distinct highlighted section at the top of the report and include them in the PDF export.
- Explain the extra API cost and let it be disabled via config.

Handoff Report: tell the human to restart both servers and run a review on a drawing likely to have overlapping requirements. Verification: conflicts section appears when relevant, conflicts are in the export, detection can be toggled off. **Then instruct the human to make the final Git commit.** Confirm the project is complete.

---

## Appendix — Everyday Run Commands (include in your final Handoff Report)

Two terminal tabs, every session:

**Backend:**
```
cd ~/compliance-reviewer/backend
source .venv/bin/activate
uvicorn main:app --reload
```
**Frontend:**
```
cd ~/compliance-reviewer/frontend
npm run dev
```
Then open `http://localhost:3000`.

**Re-ingesting when an agency updates a document:**
```
cd ~/compliance-reviewer/backend
source .venv/bin/activate
python scripts/ingest.py --agency <agency> --reset
```

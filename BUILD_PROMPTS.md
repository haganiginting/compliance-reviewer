# AI Architecture Compliance Reviewer — Agent Build Instructions

> **Agent: read this header before doing anything.**
>
> You are an agentic coding assistant building a project for a **beginner** developer on **macOS**. This document is your complete build specification. The human will reference this whole file to you across sessions — they will NOT copy-paste individual sections. You are responsible for tracking progress and knowing which sub-phase comes next.
>
> **Agent operating guide:** this repo now has `AGENTS.md`. Before acting on any future phase prompt, read `AGENTS.md` first, then return here for the detailed roadmap, acceptance criteria, and current progress notes. Keep `BUILD_PROMPTS.md` as the phase-by-phase source of truth. After each completed sub-phase, update the relevant project-state note in this file. Keep `AGENTS.md` stable unless the project-level operating rules change.
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
│       │   ├── bca/  scdf/  ura/  lta/  nparks/  nea/  pub/
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
- `app/config.py`: loads env vars from the root `.env` via python-dotenv; defines the 7 supported agencies (BCA, SCDF, URA, LTA, NParks, NEA, PUB) each with a short description and a `core` boolean (True for BCA/SCDF/URA); defines a single `CLAUDE_MODEL` constant (use a cost-effective model for development).
- Create the full empty package structure (`app/pdf/`, `app/rag/`, `app/review/`, `app/storage/`, `app/api/`, `scripts/`, and the seven `data/source_pdfs/<agency>/` folders), each Python package with an `__init__.py`.

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

> **Project state note after Sub-Phase 1.2 (2026-06-04):**
> Sub-Phase 1.2 has been implemented with a PyMuPDF parser, Pydantic parse-result models, per-page PNG rendering at 150 DPI, base64 image payloads for future Claude vision use, and a summary-only CLI at `python -m app.pdf.parse <path-to-pdf>`. Continue future work from Sub-Phase 1.3 — Knowledge Base Ingestion (BCA, SCDF, URA), after the human confirms the PDF parser CLI works on their sample PDF.

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

> **Project state note after Sub-Phase 1.3 (2026-06-04):**
> Sub-Phase 1.3 has been implemented with local ChromaDB collections per agency, free local HuggingFace embeddings, section-aware PDF text chunking, idempotent per-PDF upserts, an ingestion CLI at `python scripts/ingest.py`, and a retrieval sanity-check CLI at `python scripts/retrieve.py`. Continue future work from Sub-Phase 1.4 — Compliance Review Engine (Phase 1 milestone), after the human confirms BCA/SCDF/URA PDFs have been sorted and ingestion/retrieval verification passes.

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

> **Project state note after Sub-Phase 1.4 (2026-06-06):**
> Sub-Phase 1.4 has been implemented with a structured review schema, editable Claude system prompt, async BCA/SCDF/URA review engine, validated Claude JSON with one corrective retry, and a CLI at `python -m app.review.run <path-to-pdf>` that prints and writes the compliance report JSON. Phase 1 is ready for human verification on a real drawing PDF, cited-clause spot checks, and the Phase 1 Git commit. Continue future work from Sub-Phase 2.1 — Ingest Remaining 4 Agencies, after the human confirms Phase 1 verification passes and the LTA/NParks/NEA/PUB PDFs are ready to sort.

---

# PHASE 2 — Full Coverage + Web UI

**Goal:** upload a PDF in the browser, get a full 7-agency report, filterable and exportable. Split into 5 sub-phases.

---

## Sub-Phase 2.1 — Ingest Remaining 4 Agencies

Extend the knowledge base from 3 to 7 agencies (the ingest code is already generic).

- Confirm ingestion handles `lta`, `nparks`, `nea`, `pub` → collections `sg_lta`, `sg_nparks`, `sg_nea`, `sg_pub`.
- Update `app/review` to loop over a CONFIGURABLE active-agency list (default: all 7 supported agencies) instead of the hardcoded 3.
- Drive the active-agency list from `app/config.py` so agencies can be toggled in one place.
- Update the JSON report + summary to cover all 7.

Handoff Report: tell the human to sort the 4 new agency PDF sets into their folders, run ingestion per agency, and re-run a CLI review. Verification: all 7 collections non-empty, a CLI review returns up to 7 agencies, toggling an agency off in config removes it next run.

> **Project state note after Sub-Phase 2.1 (2026-06-06):**
> Sub-Phase 2.1 has been implemented with a configurable `ACTIVE_AGENCY_CODES` list in `app/config.py`, default ingestion/review coverage for the 7 supported agencies, and updated CLI wording. Continue future work from Sub-Phase 2.2 — Backend API + SQLite Storage, after the human confirms LTA/NParks/NEA/PUB PDFs have been sorted, ingested, and verified with a 7-agency CLI review.

---

## Sub-Phase 2.2 — Backend API + SQLite Storage

Expose the review engine over HTTP via FastAPI in `backend/app/api/`, and build SQLite storage in `backend/app/storage/`.

- `POST /api/reviews` — accepts a multipart PDF upload, starts a review as a background task, returns a `review_id` immediately (do not block for minutes).
- `GET /api/reviews/{review_id}` — returns status (`processing|done|error`) and, when done, the full report.
- `GET /api/reviews` — lists past reviews (id, filename, created_at, total_issues, status).
- Implement SQLite (SQLModel or plain sqlite3 — pick one and explain) with `reviews` and `issues` tables; persist every completed report.
- Enable CORS for `localhost:3000` (explain what CORS is in a comment).

Handoff Report: tell the human how to start the backend and test each endpoint with `curl`, including uploading a PDF via `curl -F` (explain `-F` and `@`). Verification: upload returns a `review_id` fast, polling reaches `done` with the full report, `app.db` exists and the review survives a server restart, the list endpoint shows it.

> **Project state note after Sub-Phase 2.2 (2026-06-06):**
> Sub-Phase 2.2 has been implemented with FastAPI review upload/list/detail endpoints, background review execution, CORS for the local Next.js frontend, local SQLite storage for review status/results/issues, and a git-ignored upload folder for private PDFs. Continue future work from Sub-Phase 2.3 — Upload UI & Project Dashboard, after the human confirms backend dependencies are installed and the curl endpoint verification passes.

---

## Sub-Phase 2.3 — Upload UI & Project Dashboard

Build the upload + dashboard UI in `frontend/` with Next.js App Router + Tailwind.

- Dashboard page: drag-and-drop PDF upload zone + project type selector (Residential / Commercial / Industrial / Mixed) + a list of past reviews from `GET /api/reviews` (filename, date, total issues, status badge).
- On upload: `POST /api/reviews`, then show a processing state that polls `GET /api/reviews/{id}` every few seconds until done, then routes to the report page.
- A typed API client in `src/lib/`.
- Clean, professional, neutral styling. No auth, no login.
- Use `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`) for the API URL.

Handoff Report: tell the human to create `frontend/.env.local` with `NEXT_PUBLIC_API_BASE` (explain what `.env.local` is), run both servers, and drag in a PDF. Verification: upload works and shows a processing state, finishing navigates onward, the dashboard lists past reviews.

> **Project state note after Sub-Phase 2.3 (2026-06-07):**
> Sub-Phase 2.3 has been implemented with a typed frontend API client, dashboard upload UI, project type selector, review polling, past-review list, and a minimal `/reviews/[id]` placeholder route. Project type is UI-only for now because the current backend upload endpoint accepts only the PDF. Continue future work from Sub-Phase 2.4 — Compliance Report View, Filtering & Notes, after the human confirms both servers run locally, upload/polling works, completion routes to the placeholder report page, and the dashboard lists past reviews.

---

## Sub-Phase 2.4 — Compliance Report View, Filtering & Notes

Build the report view in `frontend/` on `/reviews/[id]`.

- Fetch the full report from `GET /api/reviews/{id}`.
- Summary bar: total issues, counts per agency (colour-coded per the roadmap palette), counts per severity.
- Issues grouped by agency, colour-coded; each issue card shows title, severity tag, description, clause reference, drawing location, and an expandable "Suggested Resolution".
- Agency filter chips and severity filter to show/hide issues.
- Per-issue personal notes saved to the backend: add `PATCH /api/issues/{id}/note` and a `note` column on the issues table.

Handoff Report: tell the human to restart the backend (new routes), open a finished review, exercise filters, add a note, and reload to confirm it persisted. Verification: grouped colour-coded issues + working summary bar, filters work, a note survives reload.

> **Project state note after Sub-Phase 2.4 (2026-06-07):**
> Sub-Phase 2.4 has been implemented with a full `/reviews/[id]` compliance report view, grouped and colour-coded agency issue sections, summary counts, agency/severity filters, expandable suggested resolutions, and persistent per-issue personal notes saved through `PATCH /api/issues/{id}/note`. Existing SQLite databases migrate an `issues.note` column on backend startup, and completed review responses now include issue IDs and notes for the frontend. Continue future work from Sub-Phase 2.5 — PDF Report Export (Phase 2 milestone), after the human confirms backend restart, report filtering, note saving, and note persistence after reload.

---

## Sub-Phase 2.5 — PDF Report Export (Phase 2 milestone)

Add one-click PDF export.

- Backend-generated for consistency: `GET /api/reviews/{id}/export.pdf` rendering a clean report (filename + date, summary table, then a section per agency listing issues with severity, clause reference, description, resolution, and any personal note). Use reportlab or weasyprint — pick one and explain the tradeoff.
- An "Export PDF" button on the report page that downloads it.

Handoff Report: tell the human to restart the backend, click Export PDF, and open the file. Verification: PDF opens and is readable with summary + per-agency sections, notes appear, severities/clauses render. **Then instruct the human to make the Phase 2 Git commit.** State the Phase 3 prerequisite: collect 1-3 known-answer sample drawings for prompt/retrieval tuning.

> **Project state note after Sub-Phase 2.5 (2026-06-07):**
> Sub-Phase 2.5 has been implemented with an on-demand ReportLab PDF renderer, `GET /api/reviews/{id}/export.pdf`, and an Export PDF button on completed report pages. Exports include review metadata, summary counts, per-agency issue sections, severities, clause references, descriptions, suggested resolutions, and saved personal notes. Phase 2 is ready for human verification and the Phase 2 Git commit. Continue future work from Phase 3 — Polish, Tune & Conflict Detection, after the human confirms PDF export works and has 1-3 known-answer sample drawings ready for tuning.

---

# PHASE 3 — Polish, Tune, Large Sets & Conflict Detection

**Goal:** accurate and smooth enough for a real project using the 7 supported agencies, including realistic multi-page drawing sets. Split into 5 sub-phases.

---

## Sub-Phase 3.1 — Prompt & Retrieval Tuning

Improve accuracy, no new features.

- Add a lightweight eval harness: a folder of sample drawings + a YAML/JSON file of "expected findings"; a script runs reviews and reports caught/missed findings.
- Make retrieval parameters (chunk size, overlap, `top_k` per agency) configurable in `config.py`.
- Allow per-agency system-prompt overrides (especially URA development-control parameters and PUB drainage/MPL, which are number-heavy); keep prompts in editable files.
- Add structured logging of each agency's retrieved chunks per review so the human can see WHY Claude flagged something.

Handoff Report: tell the human to add 1–3 drawings they know the answers for, fill in the expected-findings file, and run the harness. Verification: harness reports caught/missed, changing `top_k`/chunk size measurably changes retrieval, logs show the clauses behind each flag.

> **Project state note after Sub-Phase 3.1 (2026-06-07):**
> Sub-Phase 3.1 has been implemented with configurable chunk size, overlap, and per-agency retrieval `top_k`; editable base and per-agency prompt files; structured retrieval trace logs under `backend/data/retrieval_logs/`; and a JSON eval harness at `python scripts/evaluate.py` using private known-answer files under `backend/data/evals/`. During eval, a realistic multi-page drawing set hit the current single-request image payload limit, so the next implementation work should start from Sub-Phase 3.2 — Large Drawing Set Handling & Upload Context, after the human confirms the eval harness runs on 1-3 known-answer drawings and retrieval logs show the clauses behind each review.

---

## Sub-Phase 3.2 — Large Drawing Set Handling & Upload Context

Support realistic multi-page drawing sets without sending every rendered page image in one Claude request.

- Add frontend upload context fields: drawing type (Floor Plan / Site Plan / Section & Elevation / Drainage / Fire Safety / Mixed Set), a short user description, and optional review notes.
- Extend the backend upload API and SQLite storage to persist drawing type, description, and notes with each review.
- Update the review engine to process large PDFs in page/agency batches instead of one all-pages request per agency.
- Build a lightweight page inventory from parsed text, labels, annotations, and the user description so each agency review sends only the most relevant page images for that batch.
- Add image budget controls in config: max image payload per Claude request, max images per batch, and a fallback to lower-DPI/compressed page images when needed.
- Keep the final report shape the same by merging batch findings into one agency report, deduplicating near-identical findings, and rebuilding the summary.
- Add clearer review progress/status messaging for long reviews (for example: parsing PDF, reviewing URA pages 1-4, combining findings).
- Ensure eval harness and API reviews both use the same large-PDF batching path.

Handoff Report: tell the human to restart both servers, upload a larger multi-page drawing set, fill in the drawing type/description fields, and run the eval harness again on the previously failing sample. Verification: the large PDF no longer fails with the PNG payload-size error, logs show page/agency batches, the final report still has the same agency/issue/summary shape, and changing the description can influence page selection/retrieval without inventing unsupported findings.

> **Project state note after Sub-Phase 3.2 (2026-06-07):**
> Sub-Phase 3.2 has been implemented with upload context fields for drawing type, description, and review notes; SQLite storage/migration for review context and live status messages; batched page/agency review handling with per-request image budgets and lower-DPI PNG fallback; batch-aware retrieval trace logs; merged/deduplicated agency findings that preserve the existing report shape; and frontend progress messaging driven by backend status. Continue future work from Sub-Phase 3.3 — Review Scope Controls & Inline PDF Viewer, after the human confirms a larger multi-page drawing set no longer fails with the single-request PNG payload-size error and the eval harness uses the batched path.

---

## Sub-Phase 3.3 — Review Scope Controls & Inline PDF Viewer

Add review scope controls to reduce waiting time/token cost, improve prompt accuracy by submission stage, and add an inline viewer on the report page.

- Before upload, require the user to choose which agencies to review against (BCA / SCDF / URA / LTA / NParks / NEA / PUB), defaulting to all active agencies but allowing one or many. Persist the selected agencies with the review and use them in API reviews, CLI/eval reviews where applicable, summaries, reports, logs, and PDF export.
- Before upload, require the user to choose drawing submission type: Design / Authority Submission. Persist this with each review.
- Update backend review context, prompts, and Claude user instructions so Design drawings still receive design-compliance checks but ignore authority-submission drawing-format requirements such as missing north arrow, missing scale bar, title-block/submission completeness, and other authority-documentation-only items unless the selected submission type is Authority Submission.
- Keep authority/submission drawing requirements active when the selected submission type is Authority Submission.
- Update frontend dashboard upload UI, typed API client, SQLite storage, list/detail responses, report metadata, and export metadata for selected agencies and submission type.
- Make review progress/status messages reflect the selected agency list so the user understands why a shorter review is faster.
- Serve the original PDF from the backend: `GET /api/reviews/{id}/file`.
- Embed a viewer in a split-pane layout: report one side, drawing the other.
- Clicking an issue with a drawing_location/page jumps the viewer to that page.
- Explain the viewer choice and whether it adds any new dependency.

Handoff Report: tell the human to restart both servers, run one review against a single agency, run one review against multiple agencies, compare time/token behavior, test both Design and Authority Submission modes on the same drawing, then open a report and click an issue. Verification: selected agencies are the only agencies reviewed and displayed, Design mode suppresses authority-submission drawing-format findings while keeping design-compliance findings, Authority Submission mode can still flag drawing-format/submission-completeness issues, the drawing renders in the split pane, and clicking an issue navigates to the cited page.

> **Project state note after Sub-Phase 3.3 (2026-06-09):**
> Sub-Phase 3.3 has been implemented with pre-upload agency scope controls, Design/Authority Submission selection, persisted review scope metadata, scoped API/CLI/eval reviews, submission-aware prompt guidance, stored drawing page numbers, inline original-PDF serving at `GET /api/reviews/{id}/file`, ReportLab export metadata, and a split-pane browser-native PDF iframe layout with issue-to-page navigation. The first React PDF Viewer implementation was replaced with the native iframe viewer after local rendering showed a blank PDF pane, so there is no added PDF viewer dependency. Continue future work from Sub-Phase 3.4 — PDF Issue Markup & Strict Drawing-Scope Review, after the human confirms single-agency and multi-agency reviews, Design versus Authority Submission behavior, the inline PDF viewer, and issue page jumps all work locally.

---

## Sub-Phase 3.4 — PDF Issue Markup & Strict Drawing-Scope Review

Add visible issue markup to the PDF viewer and tighten review behavior so Claude only comments on the uploaded drawing evidence and selected review scope.

- Replace or augment the current native iframe PDF viewer with a controllable page-image viewer using backend-rendered PDF page images, for example `GET /api/reviews/{id}/pages/{page_number}.png`. The viewer must still work locally and must not expose private PDFs outside the local backend.
- Add dynamic issue markup overlays on the displayed page. Use reliable numbered markers as the first milestone, not fake exact bounding boxes. Each marker should correlate to one issue/comment, show severity colour and agency label, and appear only on the cited page.
- Link report cards and PDF markers both ways: clicking an issue jumps to the right page and highlights the matching marker; clicking a marker scrolls or selects the matching issue card.
- Extend issue data where useful with optional markup metadata in review responses, SQLite storage/hydration, frontend types, and PDF export. Keep fallback behavior when only `drawing_page_number` or parseable `drawing_location` exists. Suggested optional fields: `page_number`, `marker_label`, `severity`, `agency`, and optional normalized marker position.
- Keep the existing issue-to-page jump behavior as a fallback for older reviews and issues that do not have full markup metadata.
- Tighten the base system prompt and per-request user instructions with a hard "uploaded drawing evidence only" rule: review only the pages, labels, text, and images actually uploaded for this review, plus the selected agencies, drawing type, submission type, description, and review notes.
- Do not flag missing specifications, forms, schedules, reports, calculations, material specs, title blocks, signatures, complete drawing sets, or authority-submission documentation unless those materials are actually uploaded and the selected submission type makes those checks in scope.
- Treat drawing type and submission type as hard scope controls. If the user uploads a single-page Floor Plan in Design mode for SCDF, the review should only make SCDF design-compliance comments that can be assessed from that floor plan and directly supported by retrieved clauses.
- Keep Authority Submission requirements active only when submission type is Authority Submission and the uploaded evidence supports that review.

Handoff Report: tell the human to restart both servers, open a completed report, click issue cards and PDF markers in both directions, then run the known one-page SCDF Floor Plan test in Design mode. Verification: markers appear only on the cited pages, clicking an issue highlights the matching marker, clicking a marker selects or scrolls to the matching issue, older reviews still jump by page when marker metadata is missing, and the SCDF-only Design-mode floor plan review does not produce Authority Submission findings or comments about non-uploaded specifications/documents.

> **Project state note after Sub-Phase 3.4 (2026-06-09):**
> Sub-Phase 3.4 has been implemented with backend-rendered review page PNGs at `GET /api/reviews/{id}/pages/{page_number}.png`, deterministic issue marker metadata stored and hydrated through SQLite, a split-pane page-image viewer with issue/marker two-way selection, marker metadata in PDF exports, and stricter uploaded-evidence-only review prompt guidance. Continue future work from corrective Sub-Phase 3.4a — Drawing Understanding Gate, after the human confirms marker navigation, older-review page fallback, and the SCDF-only Design-mode floor plan scope test.

---

## Sub-Phase 3.4a — Drawing Understanding Gate

Add a pre-review drawing understanding gate so Claude reviews a confirmed page/view inventory before compliance findings are generated.

- Store `inventory_status`, `drawing_inventory_json`, and confirmation metadata with each review.
- Build a per-page drawing inventory with page number, sheet title, drawing number, primary view type, detected view types, confidence, evidence labels, and warnings.
- Classify pages using deterministic text/label heuristics first, then Claude vision with 150 DPI page images and higher-detail crops for uncertain pages.
- Pause reviews when any page is low-confidence or `Unknown`; let the frontend show thumbnails and editable view-type controls before the compliance review starts.
- Auto-confirm high-confidence inventories and continue into the existing compliance review path.
- Pass the confirmed drawing inventory into every Claude review batch.
- Add `drawing_view_type` to issue data and reject/retry findings that conflict with confirmed page view types, such as calling a confirmed section page a floor plan.
- Keep the existing report shape otherwise, including markers, notes, export, and selected-agency behavior.
- Fix review image selection so 150 DPI page images are preferred when they fit the request budget, with lower DPI fallback only when needed.
- Extend eval results with forbidden wording checks for drawing-type regressions.

Handoff Report: tell the human to restart both servers, upload the drawing set that produced the section/floor-plan confusion, correct any uncertain page labels, confirm the drawing check, and rerun the SCDF review. Verification: page 9 is classified as `Section`, low-confidence pages pause before review, confirmed high-confidence pages can auto-run, issue cards/export show drawing view type, and SCDF findings on section pages no longer call them floor plans.

> **Project state note after Sub-Phase 3.4a (2026-06-09):**
> Sub-Phase 3.4a has been implemented with a drawing inventory gate, SQLite inventory storage/migration, inventory confirmation API endpoints, frontend drawing-check screen, confirmed-inventory prompt guidance, `drawing_view_type` issue metadata, drawing-view consistency retry/drop logic, 150 DPI-first review image selection, classifier unit tests, and eval forbidden-phrase checks. Continue future work from Sub-Phase 3.5 — Cross-Agency Conflict Detection (final milestone), after the human confirms the screenshot regression no longer occurs and the drawing-check gate behaves correctly on low-confidence pages.

---

## Sub-Phase 3.5 — Cross-Agency Conflict Detection (final milestone)

Add conflict detection as the final polish.

- After all agency reviews complete, run an additional Claude pass over the combined issue list to identify cases where two agencies impose conflicting requirements on the SAME element (e.g. BCA setback vs PUB drainage reserve; LTA road reserve vs URA setback).
- Output a `conflicts` array: `{ element, agencies_involved, description, recommended_action: "seek authority pre-consultation" }`.
- Show conflicts in a distinct highlighted section at the top of the report and include them in the PDF export.
- Explain the extra API cost and let it be disabled via config.

Handoff Report: tell the human to restart both servers and run a review on a drawing likely to have overlapping requirements. Verification: conflicts section appears when relevant, conflicts are in the export, detection can be toggled off. **Then instruct the human to make the final Git commit after Sub-Phase 3.5.** Confirm the project is complete.

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

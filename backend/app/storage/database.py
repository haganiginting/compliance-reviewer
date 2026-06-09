from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import ACTIVE_AGENCY_CODES, AGENCIES, DATABASE_PATH, UPLOADS_DIR
from app.pdf.models import DrawingInventory
from app.review.models import ComplianceReport


def init_db(db_path: Path = DATABASE_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('processing', 'done', 'error')),
                drawing_type TEXT NOT NULL DEFAULT 'Mixed Set',
                description TEXT NOT NULL DEFAULT '',
                review_notes TEXT NOT NULL DEFAULT '',
                selected_agencies_json TEXT NOT NULL DEFAULT '[]',
                submission_type TEXT NOT NULL DEFAULT 'Design',
                upload_filename TEXT NOT NULL DEFAULT '',
                status_message TEXT NOT NULL DEFAULT 'Waiting to start',
                inventory_status TEXT NOT NULL DEFAULT 'pending',
                drawing_inventory_json TEXT,
                inventory_confirmed_at TEXT,
                inventory_confirmed_by TEXT,
                total_issues INTEGER NOT NULL DEFAULT 0,
                report_json TEXT,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS issues (
                id TEXT PRIMARY KEY,
                review_id TEXT NOT NULL,
                agency TEXT NOT NULL,
                title TEXT NOT NULL,
                severity TEXT NOT NULL,
                description TEXT NOT NULL,
                clause_reference TEXT NOT NULL,
                drawing_location TEXT NOT NULL,
                drawing_page_number INTEGER,
                drawing_view_type TEXT,
                markup_page_number INTEGER,
                marker_label TEXT,
                marker_x REAL,
                marker_y REAL,
                suggested_resolution TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (review_id) REFERENCES reviews(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_reviews_created_at ON reviews(created_at);
            CREATE INDEX IF NOT EXISTS idx_issues_review_id ON issues(review_id);
            """
        )
        _ensure_issue_note_column(connection)
        _ensure_issue_markup_columns(connection)
        _ensure_review_context_columns(connection)


def create_review(
    review_id: str,
    filename: str,
    drawing_type: str = "Mixed Set",
    description: str = "",
    review_notes: str = "",
    selected_agencies: list[str] | tuple[str, ...] | None = None,
    submission_type: str = "Design",
    upload_filename: str = "",
    db_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    now = _utc_now()
    agency_codes = _normalize_stored_agencies(selected_agencies)
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO reviews (
                id,
                filename,
                created_at,
                updated_at,
                status,
                drawing_type,
                description,
                review_notes,
                selected_agencies_json,
                submission_type,
                upload_filename,
                status_message
            )
            VALUES (?, ?, ?, ?, 'processing', ?, ?, ?, ?, ?, ?, 'Waiting to start')
            """,
            (
                review_id,
                filename,
                now,
                now,
                drawing_type,
                description.strip(),
                review_notes.strip(),
                json.dumps(agency_codes),
                submission_type,
                upload_filename,
            ),
        )
    return {
        "id": review_id,
        "filename": filename,
        "created_at": now,
        "updated_at": now,
        "status": "processing",
        "drawing_type": drawing_type,
        "description": description.strip(),
        "review_notes": review_notes.strip(),
        "selected_agencies": agency_codes,
        "submission_type": submission_type,
        "upload_filename": upload_filename,
        "status_message": "Waiting to start",
        "inventory_status": "pending",
        "drawing_inventory": None,
        "inventory_confirmed_at": None,
        "inventory_confirmed_by": None,
        "total_issues": 0,
        "report": None,
        "error_message": None,
    }


def mark_review_done(review_id: str, report: ComplianceReport, db_path: Path = DATABASE_PATH) -> None:
    report_data = _model_to_dict(report)
    report_json = json.dumps(report_data)
    now = _utc_now()
    issue_rows = _issue_rows_from_report(review_id, report_data)

    with _connect(db_path) as connection:
        connection.execute("DELETE FROM issues WHERE review_id = ?", (review_id,))
        connection.executemany(
            """
            INSERT INTO issues (
                id,
                review_id,
                agency,
                title,
                severity,
                description,
                clause_reference,
                drawing_location,
                drawing_page_number,
                drawing_view_type,
                markup_page_number,
                marker_label,
                marker_x,
                marker_y,
                suggested_resolution,
                note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            issue_rows,
        )
        connection.execute(
            """
            UPDATE reviews
            SET status = 'done',
                updated_at = ?,
                status_message = 'Review complete',
                total_issues = ?,
                report_json = ?,
                error_message = NULL
            WHERE id = ?
            """,
            (now, report_data["summary"]["total_issues"], report_json, review_id),
        )


def mark_review_error(review_id: str, error_message: str, db_path: Path = DATABASE_PATH) -> None:
    now = _utc_now()
    with _connect(db_path) as connection:
        connection.execute("DELETE FROM issues WHERE review_id = ?", (review_id,))
        connection.execute(
            """
            UPDATE reviews
            SET status = 'error',
                updated_at = ?,
                error_message = ?,
                status_message = ?,
                report_json = NULL
            WHERE id = ?
            """,
            (now, error_message, error_message, review_id),
        )


def mark_review_progress(review_id: str, message: str, db_path: Path = DATABASE_PATH) -> None:
    cleaned_message = message.strip() or "Processing"
    now = _utc_now()
    with _connect(db_path) as connection:
        connection.execute(
            """
            UPDATE reviews
            SET updated_at = ?,
                status_message = ?
            WHERE id = ? AND status = 'processing'
            """,
            (now, cleaned_message, review_id),
        )


def update_review_inventory(
    review_id: str,
    inventory: DrawingInventory,
    inventory_status: str,
    confirmed_by: str | None = None,
    status_message: str | None = None,
    db_path: Path = DATABASE_PATH,
) -> dict[str, Any] | None:
    if inventory_status not in {"pending", "needs_confirmation", "confirmed", "error"}:
        raise ValueError("Invalid inventory status.")

    inventory_data = _inventory_to_dict(inventory)
    now = _utc_now()
    confirmed_at = now if inventory_status == "confirmed" else None
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT id FROM reviews WHERE id = ?",
            (review_id,),
        ).fetchone()
        if row is None:
            return None

        connection.execute(
            """
            UPDATE reviews
            SET updated_at = ?,
                inventory_status = ?,
                drawing_inventory_json = ?,
                inventory_confirmed_at = ?,
                inventory_confirmed_by = ?,
                status_message = COALESCE(?, status_message)
            WHERE id = ?
            """,
            (
                now,
                inventory_status,
                json.dumps(inventory_data),
                confirmed_at,
                confirmed_by if inventory_status == "confirmed" else None,
                status_message,
                review_id,
            ),
        )

    return {
        "review_id": review_id,
        "inventory_status": inventory_status,
        "drawing_inventory": inventory_data,
        "inventory_confirmed_at": confirmed_at,
        "inventory_confirmed_by": confirmed_by if inventory_status == "confirmed" else None,
    }


def get_review_inventory(review_id: str, db_path: Path = DATABASE_PATH) -> dict[str, Any] | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT
                id,
                inventory_status,
                drawing_inventory_json,
                inventory_confirmed_at,
                inventory_confirmed_by
            FROM reviews
            WHERE id = ?
            """,
            (review_id,),
        ).fetchone()

    if row is None:
        return None

    review = dict(row)
    return {
        "review_id": review["id"],
        "inventory_status": review.get("inventory_status") or "pending",
        "drawing_inventory": _inventory_from_json(review.get("drawing_inventory_json")),
        "inventory_confirmed_at": review.get("inventory_confirmed_at"),
        "inventory_confirmed_by": review.get("inventory_confirmed_by"),
    }


def get_review(review_id: str, db_path: Path = DATABASE_PATH) -> dict[str, Any] | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT
                id,
                filename,
                created_at,
                updated_at,
                status,
                drawing_type,
                description,
                review_notes,
                selected_agencies_json,
                submission_type,
                upload_filename,
                status_message,
                inventory_status,
                drawing_inventory_json,
                inventory_confirmed_at,
                inventory_confirmed_by,
                total_issues,
                report_json,
                error_message
            FROM reviews
            WHERE id = ?
            """,
            (review_id,),
        ).fetchone()

        if row is None:
            return None

        review = dict(row)
        report_json = review.pop("report_json")
        selected_agencies_json = review.pop("selected_agencies_json")
        drawing_inventory_json = review.pop("drawing_inventory_json")
        review["report"] = json.loads(report_json) if report_json else None
        review["selected_agencies"] = _selected_agencies_for_review(selected_agencies_json, review["report"])
        review["submission_type"] = review.get("submission_type") or "Design"
        review["upload_filename"] = review.get("upload_filename") or ""
        review["inventory_status"] = review.get("inventory_status") or "pending"
        review["drawing_inventory"] = _inventory_from_json(drawing_inventory_json)

        if review["report"] is not None:
            review["report"] = _hydrate_report_issues(
                connection=connection,
                review_id=review_id,
                report_data=review["report"],
            )

    return review


def list_reviews(db_path: Path = DATABASE_PATH) -> list[dict[str, Any]]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                filename,
                created_at,
                drawing_type,
                description,
                review_notes,
                selected_agencies_json,
                submission_type,
                status_message,
                inventory_status,
                total_issues,
                status
            FROM reviews
            ORDER BY created_at DESC
            """
        ).fetchall()
    reviews: list[dict[str, Any]] = []
    for row in rows:
        review = dict(row)
        selected_agencies_json = review.pop("selected_agencies_json")
        review["selected_agencies"] = _selected_agencies_for_review(selected_agencies_json, None)
        review["submission_type"] = review.get("submission_type") or "Design"
        review["inventory_status"] = review.get("inventory_status") or "pending"
        reviews.append(review)
    return reviews


def resolve_review_upload_path(review_id: str, db_path: Path = DATABASE_PATH) -> Path | None:
    review = get_review(review_id, db_path=db_path)
    if review is None:
        return None

    stored_filename = str(review.get("upload_filename") or "").strip()
    if stored_filename:
        candidate = (UPLOADS_DIR / stored_filename).resolve()
        try:
            candidate.relative_to(UPLOADS_DIR.resolve())
        except ValueError:
            return None
        if candidate.exists() and candidate.is_file():
            return candidate

    for candidate in sorted(UPLOADS_DIR.glob(f"{review_id}_*.pdf")):
        if candidate.is_file():
            return candidate

    return None


def update_issue_note(issue_id: str, note: str, db_path: Path = DATABASE_PATH) -> dict[str, str] | None:
    cleaned_note = note.strip()
    now = _utc_now()

    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, review_id
            FROM issues
            WHERE id = ?
            """,
            (issue_id,),
        ).fetchone()

        if row is None:
            return None

        connection.execute(
            """
            UPDATE issues
            SET note = ?
            WHERE id = ?
            """,
            (cleaned_note, issue_id),
        )
        connection.execute(
            """
            UPDATE reviews
            SET updated_at = ?
            WHERE id = ?
            """,
            (now, row["review_id"]),
        )

    return {"id": issue_id, "note": cleaned_note}


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _ensure_issue_note_column(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(issues)").fetchall()
    }
    if "note" not in columns:
        connection.execute("ALTER TABLE issues ADD COLUMN note TEXT NOT NULL DEFAULT ''")
    if "drawing_page_number" not in columns:
        connection.execute("ALTER TABLE issues ADD COLUMN drawing_page_number INTEGER")
    if "drawing_view_type" not in columns:
        connection.execute("ALTER TABLE issues ADD COLUMN drawing_view_type TEXT")


def _ensure_issue_markup_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(issues)").fetchall()
    }
    migrations = {
        "markup_page_number": "ALTER TABLE issues ADD COLUMN markup_page_number INTEGER",
        "marker_label": "ALTER TABLE issues ADD COLUMN marker_label TEXT",
        "marker_x": "ALTER TABLE issues ADD COLUMN marker_x REAL",
        "marker_y": "ALTER TABLE issues ADD COLUMN marker_y REAL",
    }
    for column, statement in migrations.items():
        if column not in columns:
            connection.execute(statement)


def _ensure_review_context_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(reviews)").fetchall()
    }
    migrations = {
        "drawing_type": "ALTER TABLE reviews ADD COLUMN drawing_type TEXT NOT NULL DEFAULT 'Mixed Set'",
        "description": "ALTER TABLE reviews ADD COLUMN description TEXT NOT NULL DEFAULT ''",
        "review_notes": "ALTER TABLE reviews ADD COLUMN review_notes TEXT NOT NULL DEFAULT ''",
        "selected_agencies_json": "ALTER TABLE reviews ADD COLUMN selected_agencies_json TEXT NOT NULL DEFAULT '[]'",
        "submission_type": "ALTER TABLE reviews ADD COLUMN submission_type TEXT NOT NULL DEFAULT 'Design'",
        "upload_filename": "ALTER TABLE reviews ADD COLUMN upload_filename TEXT NOT NULL DEFAULT ''",
        "status_message": "ALTER TABLE reviews ADD COLUMN status_message TEXT NOT NULL DEFAULT 'Waiting to start'",
        "inventory_status": "ALTER TABLE reviews ADD COLUMN inventory_status TEXT NOT NULL DEFAULT 'pending'",
        "drawing_inventory_json": "ALTER TABLE reviews ADD COLUMN drawing_inventory_json TEXT",
        "inventory_confirmed_at": "ALTER TABLE reviews ADD COLUMN inventory_confirmed_at TEXT",
        "inventory_confirmed_by": "ALTER TABLE reviews ADD COLUMN inventory_confirmed_by TEXT",
    }
    for column, statement in migrations.items():
        if column not in columns:
            connection.execute(statement)


def _hydrate_report_issues(
    connection: sqlite3.Connection,
    review_id: str,
    report_data: dict[str, Any],
) -> dict[str, Any]:
    issue_rows = connection.execute(
        """
        SELECT
            id,
            agency,
            title,
            severity,
            description,
            clause_reference,
            drawing_location,
            drawing_page_number,
            drawing_view_type,
            markup_page_number,
            marker_label,
            marker_x,
            marker_y,
            suggested_resolution,
            note
        FROM issues
        WHERE review_id = ?
        ORDER BY rowid
        """,
        (review_id,),
    ).fetchall()
    issues_by_agency: dict[str, list[dict[str, Any]]] = {}
    page_marker_counts: dict[int, int] = {}
    agency_issue_counts: dict[str, int] = {}

    for row in issue_rows:
        issue = dict(row)
        if issue.get("drawing_page_number") is None:
            issue["drawing_page_number"] = _page_number_from_location(issue.get("drawing_location", ""))
        agency = issue.pop("agency")
        agency_issue_counts[agency] = agency_issue_counts.get(agency, 0) + 1
        issue["markup"] = _markup_from_issue_row(
            issue=issue,
            agency=agency,
            agency_issue_number=agency_issue_counts[agency],
            page_marker_counts=page_marker_counts,
        )
        for storage_field in ("markup_page_number", "marker_label", "marker_x", "marker_y"):
            issue.pop(storage_field, None)
        issues_by_agency.setdefault(agency, []).append(issue)

    seen_agencies: set[str] = set()
    for agency_report in report_data.get("agencies", []):
        agency = agency_report.get("agency", "")
        seen_agencies.add(agency)
        agency_report["issues"] = issues_by_agency.get(agency, [])

    for agency, issues in issues_by_agency.items():
        if agency not in seen_agencies:
            report_data.setdefault("agencies", []).append(
                {
                    "agency": agency,
                    "issues": issues,
                }
            )

    return report_data


def _issue_rows_from_report(
    review_id: str,
    report_data: dict[str, Any],
) -> list[tuple[str, str, str, str, str, str, str, str, int | None, str | None, int | None, str | None, float | None, float | None, str, str]]:
    rows: list[
        tuple[
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            int | None,
            str | None,
            int | None,
            str | None,
            float | None,
            float | None,
            str,
            str,
        ]
    ] = []
    page_marker_counts: dict[int, int] = {}
    for agency in report_data["agencies"]:
        agency_name = agency["agency"]
        for issue_number, issue in enumerate(agency["issues"], start=1):
            drawing_page_number = issue.get("drawing_page_number")
            if drawing_page_number is None:
                drawing_page_number = _page_number_from_location(issue.get("drawing_location", ""))
            markup = _build_issue_markup(
                issue=issue,
                agency=agency_name,
                agency_issue_number=issue_number,
                drawing_page_number=drawing_page_number,
                page_marker_counts=page_marker_counts,
            )
            rows.append(
                (
                    str(uuid.uuid4()),
                    review_id,
                    agency_name,
                    issue["title"],
                    issue["severity"],
                    issue["description"],
                    issue["clause_reference"],
                    issue["drawing_location"],
                    drawing_page_number,
                    issue.get("drawing_view_type"),
                    markup["page_number"] if markup else None,
                    markup["marker_label"] if markup else None,
                    markup["marker_x"] if markup else None,
                    markup["marker_y"] if markup else None,
                    issue["suggested_resolution"],
                    "",
                )
            )
    return rows


def _markup_from_issue_row(
    issue: dict[str, Any],
    agency: str,
    agency_issue_number: int,
    page_marker_counts: dict[int, int],
) -> dict[str, Any] | None:
    stored_page_number = issue.get("markup_page_number")
    page_number = stored_page_number or issue.get("drawing_page_number")
    if page_number is None:
        return None

    marker_label = str(issue.get("marker_label") or "").strip() or _marker_label(agency, agency_issue_number)
    marker_x = _normalized_marker_value(issue.get("marker_x"))
    marker_y = _normalized_marker_value(issue.get("marker_y"))
    if marker_x is None or marker_y is None:
        marker_x, marker_y = _next_marker_position(int(page_number), page_marker_counts)
    else:
        page_marker_counts[int(page_number)] = page_marker_counts.get(int(page_number), 0) + 1

    return {
        "page_number": int(page_number),
        "marker_label": marker_label,
        "marker_x": marker_x,
        "marker_y": marker_y,
    }


def _build_issue_markup(
    issue: dict[str, Any],
    agency: str,
    agency_issue_number: int,
    drawing_page_number: int | None,
    page_marker_counts: dict[int, int],
) -> dict[str, Any] | None:
    provided_markup = issue.get("markup") if isinstance(issue.get("markup"), dict) else {}
    page_number = provided_markup.get("page_number") or drawing_page_number
    if page_number is None:
        return None

    marker_x = _normalized_marker_value(provided_markup.get("marker_x"))
    marker_y = _normalized_marker_value(provided_markup.get("marker_y"))
    if marker_x is None or marker_y is None:
        marker_x, marker_y = _next_marker_position(int(page_number), page_marker_counts)

    return {
        "page_number": int(page_number),
        "marker_label": str(provided_markup.get("marker_label") or "").strip()
        or _marker_label(agency, agency_issue_number),
        "marker_x": marker_x,
        "marker_y": marker_y,
    }


def _next_marker_position(page_number: int, page_marker_counts: dict[int, int]) -> tuple[float, float]:
    marker_index = page_marker_counts.get(page_number, 0)
    page_marker_counts[page_number] = marker_index + 1
    column = marker_index // 12
    row = marker_index % 12
    return min(0.08 + (column * 0.08), 0.88), min(0.12 + (row * 0.06), 0.88)


def _marker_label(agency: str, issue_number: int) -> str:
    safe_agency = re.sub(r"[^A-Za-z0-9]+", "", agency).upper() or "ISSUE"
    return f"{safe_agency}-{issue_number}"


def _normalized_marker_value(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number > 1:
        return None
    return number


def _model_to_dict(model: ComplianceReport) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _inventory_to_dict(inventory: DrawingInventory) -> dict[str, Any]:
    if hasattr(inventory, "model_dump"):
        return inventory.model_dump()
    return inventory.dict()


def _inventory_from_json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    return None


def _normalize_stored_agencies(value: list[str] | tuple[str, ...] | None) -> list[str]:
    active_codes = tuple(code.lower().strip() for code in ACTIVE_AGENCY_CODES)
    if value is None:
        return list(active_codes)

    normalized: list[str] = []
    for code in value:
        cleaned_code = str(code).lower().strip()
        if cleaned_code in active_codes and cleaned_code not in normalized:
            normalized.append(cleaned_code)
    return normalized or list(active_codes)


def _selected_agencies_for_review(selected_agencies_json: str, report_data: dict[str, Any] | None) -> list[str]:
    try:
        stored_codes = json.loads(selected_agencies_json or "[]")
    except json.JSONDecodeError:
        stored_codes = []

    normalized = _normalize_stored_agencies(stored_codes)
    if stored_codes:
        return normalized

    agency_codes_from_report: list[str] = []
    for agency_report in (report_data or {}).get("agencies", []):
        agency_name = str(agency_report.get("agency", "")).lower().strip()
        for code, agency in AGENCIES.items():
            if agency.name.lower() == agency_name and code in ACTIVE_AGENCY_CODES:
                agency_codes_from_report.append(code)
                break
    return _normalize_stored_agencies(agency_codes_from_report or None)


def _page_number_from_location(location: str) -> int | None:
    match = re.search(r"\b(?:page|pg\.?|p\.)\s*#?\s*(\d+)\b", str(location), flags=re.IGNORECASE)
    if match is None:
        return None
    page_number = int(match.group(1))
    if page_number < 1:
        return None
    return page_number


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

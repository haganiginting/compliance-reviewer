from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import DATABASE_PATH
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
                suggested_resolution TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (review_id) REFERENCES reviews(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_reviews_created_at ON reviews(created_at);
            CREATE INDEX IF NOT EXISTS idx_issues_review_id ON issues(review_id);
            """
        )
        _ensure_issue_note_column(connection)


def create_review(review_id: str, filename: str, db_path: Path = DATABASE_PATH) -> dict[str, Any]:
    now = _utc_now()
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO reviews (id, filename, created_at, updated_at, status)
            VALUES (?, ?, ?, ?, 'processing')
            """,
            (review_id, filename, now, now),
        )
    return {
        "id": review_id,
        "filename": filename,
        "created_at": now,
        "updated_at": now,
        "status": "processing",
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
                suggested_resolution,
                note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            issue_rows,
        )
        connection.execute(
            """
            UPDATE reviews
            SET status = 'done',
                updated_at = ?,
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
                report_json = NULL
            WHERE id = ?
            """,
            (now, error_message, review_id),
        )


def get_review(review_id: str, db_path: Path = DATABASE_PATH) -> dict[str, Any] | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, filename, created_at, updated_at, status, total_issues, report_json, error_message
            FROM reviews
            WHERE id = ?
            """,
            (review_id,),
        ).fetchone()

        if row is None:
            return None

        review = dict(row)
        report_json = review.pop("report_json")
        review["report"] = json.loads(report_json) if report_json else None

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
            SELECT id, filename, created_at, total_issues, status
            FROM reviews
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


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
            suggested_resolution,
            note
        FROM issues
        WHERE review_id = ?
        ORDER BY rowid
        """,
        (review_id,),
    ).fetchall()
    issues_by_agency: dict[str, list[dict[str, Any]]] = {}

    for row in issue_rows:
        issue = dict(row)
        agency = issue.pop("agency")
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


def _issue_rows_from_report(review_id: str, report_data: dict[str, Any]) -> list[tuple[str, str, str, str, str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str, str, str, str, str]] = []
    for agency in report_data["agencies"]:
        for issue in agency["issues"]:
            rows.append(
                (
                    str(uuid.uuid4()),
                    review_id,
                    agency["agency"],
                    issue["title"],
                    issue["severity"],
                    issue["description"],
                    issue["clause_reference"],
                    issue["drawing_location"],
                    issue["suggested_resolution"],
                    "",
                )
            )
    return rows


def _model_to_dict(model: ComplianceReport) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

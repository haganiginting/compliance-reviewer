"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getReviewExportUrl,
  getReview,
  updateIssueNote,
  type AgencyReview,
  type ComplianceIssue,
  type ComplianceReport,
  type ReviewDetail,
  type ReviewStatus,
  type Severity
} from "@/lib/api";

type ReviewReportProps = {
  reviewId: string;
};

type AgencyFilter = "all" | string;
type SeverityFilter = "all" | Severity;
type NoteState = "idle" | "saving" | "saved" | "error";

const SEVERITIES: Severity[] = ["Critical", "Major", "Advisory"];

const AGENCY_PALETTE: Record<
  string,
  { border: string; bg: string; text: string; softBg: string; stripe: string }
> = {
  BCA: {
    border: "border-teal-300",
    bg: "bg-teal-700",
    text: "text-teal-900",
    softBg: "bg-teal-50",
    stripe: "border-l-teal-600"
  },
  SCDF: {
    border: "border-red-300",
    bg: "bg-red-700",
    text: "text-red-900",
    softBg: "bg-red-50",
    stripe: "border-l-red-600"
  },
  URA: {
    border: "border-indigo-300",
    bg: "bg-indigo-700",
    text: "text-indigo-900",
    softBg: "bg-indigo-50",
    stripe: "border-l-indigo-600"
  },
  LTA: {
    border: "border-amber-300",
    bg: "bg-amber-600",
    text: "text-amber-950",
    softBg: "bg-amber-50",
    stripe: "border-l-amber-500"
  },
  NParks: {
    border: "border-emerald-300",
    bg: "bg-emerald-700",
    text: "text-emerald-900",
    softBg: "bg-emerald-50",
    stripe: "border-l-emerald-600"
  },
  NEA: {
    border: "border-cyan-300",
    bg: "bg-cyan-700",
    text: "text-cyan-900",
    softBg: "bg-cyan-50",
    stripe: "border-l-cyan-600"
  },
  PUB: {
    border: "border-blue-300",
    bg: "bg-blue-700",
    text: "text-blue-900",
    softBg: "bg-blue-50",
    stripe: "border-l-blue-600"
  }
};

const DEFAULT_AGENCY_STYLE = {
  border: "border-neutral-300",
  bg: "bg-neutral-700",
  text: "text-neutral-900",
  softBg: "bg-neutral-50",
  stripe: "border-l-neutral-500"
};

export function ReviewReport({ reviewId }: ReviewReportProps) {
  const [review, setReview] = useState<ReviewDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [agencyFilter, setAgencyFilter] = useState<AgencyFilter>("all");
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("all");
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [noteStates, setNoteStates] = useState<Record<string, NoteState>>({});
  const [noteErrors, setNoteErrors] = useState<Record<string, string>>({});

  const loadReview = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const data = await getReview(reviewId);
      setReview(data);
      setNoteDrafts(draftsFromReview(data));
      setNoteStates({});
      setNoteErrors({});
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Could not load this review."
      );
    } finally {
      setLoading(false);
    }
  }, [reviewId]);

  useEffect(() => {
    void loadReview();
  }, [loadReview]);

  const report = review?.report ?? null;

  const visibleAgencies = useMemo(() => {
    if (!report) {
      return [];
    }

    return filterAgencies(report, agencyFilter, severityFilter);
  }, [agencyFilter, report, severityFilter]);

  const visibleIssueCount = useMemo(
    () =>
      visibleAgencies.reduce(
        (total, agency) => total + agency.issues.length,
        0
      ),
    [visibleAgencies]
  );

  const handleSaveNote = async (issue: ComplianceIssue) => {
    const draft = noteDrafts[issue.id] ?? "";

    setNoteStates((current) => ({ ...current, [issue.id]: "saving" }));
    setNoteErrors((current) => ({ ...current, [issue.id]: "" }));

    try {
      const updatedIssue = await updateIssueNote(issue.id, draft);
      setReview((current) =>
        current ? updateIssueInReview(current, updatedIssue.id, updatedIssue.note) : current
      );
      setNoteDrafts((current) => ({
        ...current,
        [updatedIssue.id]: updatedIssue.note
      }));
      setNoteStates((current) => ({ ...current, [updatedIssue.id]: "saved" }));
    } catch (saveError) {
      setNoteStates((current) => ({ ...current, [issue.id]: "error" }));
      setNoteErrors((current) => ({
        ...current,
        [issue.id]:
          saveError instanceof Error
            ? saveError.message
            : "Could not save this note."
      }));
    }
  };

  const handleClearNote = async (issue: ComplianceIssue) => {
    setNoteDrafts((current) => ({ ...current, [issue.id]: "" }));
    setNoteStates((current) => ({ ...current, [issue.id]: "saving" }));
    setNoteErrors((current) => ({ ...current, [issue.id]: "" }));

    try {
      const updatedIssue = await updateIssueNote(issue.id, "");
      setReview((current) =>
        current ? updateIssueInReview(current, updatedIssue.id, updatedIssue.note) : current
      );
      setNoteStates((current) => ({ ...current, [updatedIssue.id]: "saved" }));
    } catch (clearError) {
      setNoteDrafts((current) => ({ ...current, [issue.id]: issue.note }));
      setNoteStates((current) => ({ ...current, [issue.id]: "error" }));
      setNoteErrors((current) => ({
        ...current,
        [issue.id]:
          clearError instanceof Error
            ? clearError.message
            : "Could not clear this note."
      }));
    }
  };

  const handleNoteDraftChange = (issueId: string, value: string) => {
    setNoteDrafts((current) => ({ ...current, [issueId]: value }));
    setNoteStates((current) => ({ ...current, [issueId]: "idle" }));
    setNoteErrors((current) => ({ ...current, [issueId]: "" }));
  };

  return (
    <main className="min-h-screen bg-neutral-100 px-5 py-6 text-neutral-950 sm:px-8 lg:px-10">
      <div className="mx-auto w-full max-w-7xl">
        <Link
          className="text-sm font-medium text-teal-800 hover:text-teal-950"
          href="/"
        >
          Back to dashboard
        </Link>

        <section className="mt-5 border border-neutral-300 bg-white p-5 shadow-sm sm:p-6">
          {loading ? (
            <StateMessage
              title="Loading report"
              body="Fetching the stored review from the local backend."
            />
          ) : error ? (
            <StateMessage
              tone="error"
              title="Could not load report"
              body={error}
              actionLabel="Try again"
              onAction={() => void loadReview()}
            />
          ) : review ? (
            <ReportBody
              agencyFilter={agencyFilter}
              noteDrafts={noteDrafts}
              noteErrors={noteErrors}
              noteStates={noteStates}
              onAgencyFilterChange={setAgencyFilter}
              onClearNote={handleClearNote}
              onNoteDraftChange={(issueId, value) =>
                handleNoteDraftChange(issueId, value)
              }
              onRefresh={() => void loadReview()}
              onSaveNote={handleSaveNote}
              onSeverityFilterChange={setSeverityFilter}
              review={review}
              severityFilter={severityFilter}
              visibleAgencies={visibleAgencies}
              visibleIssueCount={visibleIssueCount}
            />
          ) : null}
        </section>
      </div>
    </main>
  );
}

function ReportBody({
  agencyFilter,
  noteDrafts,
  noteErrors,
  noteStates,
  onAgencyFilterChange,
  onClearNote,
  onNoteDraftChange,
  onRefresh,
  onSaveNote,
  onSeverityFilterChange,
  review,
  severityFilter,
  visibleAgencies,
  visibleIssueCount
}: {
  agencyFilter: AgencyFilter;
  noteDrafts: Record<string, string>;
  noteErrors: Record<string, string>;
  noteStates: Record<string, NoteState>;
  onAgencyFilterChange: (agency: AgencyFilter) => void;
  onClearNote: (issue: ComplianceIssue) => void;
  onNoteDraftChange: (issueId: string, value: string) => void;
  onRefresh: () => void;
  onSaveNote: (issue: ComplianceIssue) => void;
  onSeverityFilterChange: (severity: SeverityFilter) => void;
  review: ReviewDetail;
  severityFilter: SeverityFilter;
  visibleAgencies: AgencyReview[];
  visibleIssueCount: number;
}) {
  if (review.status === "processing") {
    return (
      <StateMessage
        title="Review still processing"
        body="The backend is still reviewing this PDF. Refresh this page in a moment."
        actionLabel="Refresh"
        onAction={onRefresh}
      />
    );
  }

  if (review.status === "error") {
    return (
      <StateMessage
        tone="error"
        title="Review failed"
        body={
          review.error_message ||
          "The backend could not complete this review. Check the backend terminal logs."
        }
      />
    );
  }

  if (!review.report) {
    return (
      <StateMessage
        tone="error"
        title="Report missing"
        body="The review is marked done, but the backend did not return a report."
      />
    );
  }

  return (
    <div>
      <ReportHeader review={review} report={review.report} />
      <SummaryBar report={review.report} />
      <Filters
        agencyFilter={agencyFilter}
        onAgencyFilterChange={onAgencyFilterChange}
        onSeverityFilterChange={onSeverityFilterChange}
        report={review.report}
        severityFilter={severityFilter}
        visibleIssueCount={visibleIssueCount}
      />

      {visibleIssueCount === 0 ? (
        <div className="mt-6 border border-neutral-200 bg-neutral-50 px-4 py-8 text-sm text-neutral-600">
          No issues match the current filters.
        </div>
      ) : (
        <div className="mt-6 space-y-6">
          {visibleAgencies.map((agency) => (
            <AgencySection
              agency={agency}
              key={agency.agency}
              noteDrafts={noteDrafts}
              noteErrors={noteErrors}
              noteStates={noteStates}
              onClearNote={onClearNote}
              onNoteDraftChange={onNoteDraftChange}
              onSaveNote={onSaveNote}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ReportHeader({
  review,
  report
}: {
  review: ReviewDetail;
  report: ComplianceReport;
}) {
  return (
    <header className="flex flex-col justify-between gap-4 border-b border-neutral-200 pb-5 lg:flex-row lg:items-end">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-teal-700">
          Compliance report
        </p>
        <h1 className="mt-2 text-2xl font-semibold text-neutral-950 sm:text-3xl">
          {review.filename}
        </h1>
        <dl className="mt-3 grid gap-2 text-sm text-neutral-600 sm:grid-cols-3">
          <InfoTerm label="Status" value={<StatusBadge status={review.status} />} />
          <InfoTerm label="Created" value={formatDate(review.created_at)} />
          <InfoTerm
            label="Reviewed"
            value={formatDate(report.reviewed_at || review.updated_at)}
          />
        </dl>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row lg:flex-col lg:items-stretch">
        <div className="border border-neutral-300 bg-neutral-50 px-4 py-3 text-sm">
          <p className="font-medium text-neutral-600">Drawing pages</p>
          <p className="mt-1 text-2xl font-semibold text-neutral-950">
            {report.document.page_count}
          </p>
        </div>
        {review.status === "done" && review.report ? (
          <a
            className="inline-flex items-center justify-center border border-teal-700 bg-teal-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-teal-800"
            href={getReviewExportUrl(review.id)}
          >
            Export PDF
          </a>
        ) : null}
      </div>
    </header>
  );
}

function SummaryBar({ report }: { report: ComplianceReport }) {
  return (
    <section className="mt-5 grid gap-3 lg:grid-cols-[160px_minmax(0,1fr)_minmax(260px,0.6fr)]">
      <SummaryTile label="Total issues" value={report.summary.total_issues} />

      <div className="border border-neutral-200 bg-neutral-50 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
          By agency
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {report.agencies.map((agency) => {
            const style = agencyStyle(agency.agency);
            const count = agencyCount(report, agency);

            return (
              <span
                className={`inline-flex items-center gap-2 border px-2.5 py-1.5 text-xs font-semibold ${style.border} ${style.softBg} ${style.text}`}
                key={agency.agency}
              >
                <span className={`h-2 w-2 ${style.bg}`} />
                {agency.agency}
                <span>{count}</span>
              </span>
            );
          })}
        </div>
      </div>

      <div className="border border-neutral-200 bg-neutral-50 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
          By severity
        </p>
        <div className="mt-3 grid grid-cols-3 gap-2">
          {SEVERITIES.map((severity) => (
            <div
              className="border border-neutral-200 bg-white px-3 py-2"
              key={severity}
            >
              <p className="text-xs font-medium text-neutral-500">{severity}</p>
              <p className="mt-1 text-xl font-semibold text-neutral-950">
                {report.summary.by_severity[severity] ?? 0}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Filters({
  agencyFilter,
  onAgencyFilterChange,
  onSeverityFilterChange,
  report,
  severityFilter,
  visibleIssueCount
}: {
  agencyFilter: AgencyFilter;
  onAgencyFilterChange: (agency: AgencyFilter) => void;
  onSeverityFilterChange: (severity: SeverityFilter) => void;
  report: ComplianceReport;
  severityFilter: SeverityFilter;
  visibleIssueCount: number;
}) {
  return (
    <section className="mt-5 border border-neutral-200 bg-white p-4">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="text-sm font-semibold text-neutral-900">Agency filter</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <FilterButton
              active={agencyFilter === "all"}
              label="All agencies"
              onClick={() => onAgencyFilterChange("all")}
            />
            {report.agencies.map((agency) => (
              <FilterButton
                active={agencyFilter === agency.agency}
                key={agency.agency}
                label={agency.agency}
                onClick={() => onAgencyFilterChange(agency.agency)}
              />
            ))}
          </div>
        </div>

        <div>
          <p className="text-sm font-semibold text-neutral-900">Severity filter</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <FilterButton
              active={severityFilter === "all"}
              label="All"
              onClick={() => onSeverityFilterChange("all")}
            />
            {SEVERITIES.map((severity) => (
              <FilterButton
                active={severityFilter === severity}
                key={severity}
                label={severity}
                onClick={() => onSeverityFilterChange(severity)}
              />
            ))}
          </div>
        </div>

        <p className="text-sm text-neutral-600">
          Showing <span className="font-semibold text-neutral-950">{visibleIssueCount}</span>{" "}
          matching issues
        </p>
      </div>
    </section>
  );
}

function AgencySection({
  agency,
  noteDrafts,
  noteErrors,
  noteStates,
  onClearNote,
  onNoteDraftChange,
  onSaveNote
}: {
  agency: AgencyReview;
  noteDrafts: Record<string, string>;
  noteErrors: Record<string, string>;
  noteStates: Record<string, NoteState>;
  onClearNote: (issue: ComplianceIssue) => void;
  onNoteDraftChange: (issueId: string, value: string) => void;
  onSaveNote: (issue: ComplianceIssue) => void;
}) {
  const style = agencyStyle(agency.agency);

  return (
    <section>
      <div
        className={`flex flex-col justify-between gap-2 border px-4 py-3 sm:flex-row sm:items-center ${style.border} ${style.softBg}`}
      >
        <h2 className={`text-lg font-semibold ${style.text}`}>{agency.agency}</h2>
        <span className="text-sm font-medium text-neutral-700">
          {agency.issues.length} {agency.issues.length === 1 ? "issue" : "issues"}
        </span>
      </div>

      <div className="mt-3 space-y-3">
        {agency.issues.map((issue) => (
          <IssueCard
            agency={agency.agency}
            issue={issue}
            key={issue.id}
            noteDraft={noteDrafts[issue.id] ?? ""}
            noteError={noteErrors[issue.id]}
            noteState={noteStates[issue.id] ?? "idle"}
            onClearNote={onClearNote}
            onNoteDraftChange={onNoteDraftChange}
            onSaveNote={onSaveNote}
          />
        ))}
      </div>
    </section>
  );
}

function IssueCard({
  agency,
  issue,
  noteDraft,
  noteError,
  noteState,
  onClearNote,
  onNoteDraftChange,
  onSaveNote
}: {
  agency: string;
  issue: ComplianceIssue;
  noteDraft: string;
  noteError?: string;
  noteState: NoteState;
  onClearNote: (issue: ComplianceIssue) => void;
  onNoteDraftChange: (issueId: string, value: string) => void;
  onSaveNote: (issue: ComplianceIssue) => void;
}) {
  const agencyClasses = agencyStyle(agency);
  const noteChanged = noteDraft !== issue.note;
  const saving = noteState === "saving";

  return (
    <article
      className={`border border-l-4 border-neutral-200 bg-white p-4 shadow-sm ${agencyClasses.stripe}`}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-base font-semibold leading-6 text-neutral-950">
            {issue.title}
          </h3>
          <div className="mt-2 flex flex-wrap gap-2 text-xs font-semibold">
            <SeverityBadge severity={issue.severity} />
            <span className="border border-neutral-200 bg-neutral-50 px-2 py-1 text-neutral-700">
              {issue.clause_reference}
            </span>
          </div>
        </div>
      </div>

      <p className="mt-4 text-sm leading-6 text-neutral-700">{issue.description}</p>

      <dl className="mt-4 grid gap-3 sm:grid-cols-2">
        <InfoBlock label="Drawing location" value={issue.drawing_location} />
        <InfoBlock label="Issue ID" value={issue.id} mono />
      </dl>

      <details className="mt-4 border border-neutral-200 bg-neutral-50">
        <summary className="cursor-pointer px-3 py-2 text-sm font-semibold text-neutral-900">
          Suggested Resolution
        </summary>
        <p className="border-t border-neutral-200 px-3 py-3 text-sm leading-6 text-neutral-700">
          {issue.suggested_resolution}
        </p>
      </details>

      <div className="mt-4 border-t border-neutral-200 pt-4">
        <label
          className="text-sm font-semibold text-neutral-900"
          htmlFor={`note-${issue.id}`}
        >
          Personal note
        </label>
        <textarea
          className="mt-2 min-h-24 w-full resize-y border border-neutral-300 px-3 py-2 text-sm leading-6 text-neutral-900 outline-none transition focus:border-teal-700 focus:ring-2 focus:ring-teal-100 disabled:bg-neutral-100"
          disabled={saving}
          id={`note-${issue.id}`}
          maxLength={4000}
          onChange={(event) => onNoteDraftChange(issue.id, event.target.value)}
          placeholder="Add a reminder, follow-up, or local design note."
          value={noteDraft}
        />
        <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-neutral-500">{noteDraft.length}/4000 characters</p>
          <div className="flex gap-2">
            <button
              className="border border-neutral-300 px-3 py-2 text-sm font-medium text-neutral-800 transition hover:border-neutral-500 disabled:cursor-not-allowed disabled:bg-neutral-100 disabled:text-neutral-400"
              disabled={saving || (!noteDraft && !issue.note)}
              onClick={() => onClearNote(issue)}
              type="button"
            >
              Clear
            </button>
            <button
              className="border border-teal-700 bg-teal-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:border-neutral-300 disabled:bg-neutral-300 disabled:text-neutral-600"
              disabled={saving || !noteChanged}
              onClick={() => onSaveNote(issue)}
              type="button"
            >
              {saving ? "Saving..." : "Save note"}
            </button>
          </div>
        </div>
        <NoteFeedback error={noteError} state={noteState} />
      </div>
    </article>
  );
}

function StateMessage({
  actionLabel,
  body,
  onAction,
  title,
  tone = "neutral"
}: {
  actionLabel?: string;
  body: string;
  onAction?: () => void;
  title: string;
  tone?: "neutral" | "error";
}) {
  const className =
    tone === "error"
      ? "border-red-200 bg-red-50 text-red-900"
      : "border-neutral-200 bg-neutral-50 text-neutral-900";

  return (
    <div className={`border px-4 py-8 ${className}`}>
      <h1 className="text-xl font-semibold">{title}</h1>
      <p className="mt-2 max-w-2xl text-sm leading-6">{body}</p>
      {actionLabel && onAction ? (
        <button
          className="mt-4 border border-neutral-900 bg-neutral-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-neutral-700"
          onClick={onAction}
          type="button"
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

function SummaryTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="border border-neutral-200 bg-neutral-950 p-4 text-white">
      <p className="text-xs font-semibold uppercase tracking-wide text-neutral-300">
        {label}
      </p>
      <p className="mt-2 text-3xl font-semibold">{value}</p>
    </div>
  );
}

function InfoTerm({
  label,
  value
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
        {label}
      </dt>
      <dd className="mt-1 font-medium text-neutral-900">{value}</dd>
    </div>
  );
}

function InfoBlock({
  label,
  mono = false,
  value
}: {
  label: string;
  mono?: boolean;
  value: string;
}) {
  return (
    <div className="border border-neutral-200 bg-neutral-50 p-3">
      <dt className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
        {label}
      </dt>
      <dd
        className={`mt-1 break-words text-sm font-medium text-neutral-900 ${
          mono ? "font-mono text-xs" : ""
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

function FilterButton({
  active,
  label,
  onClick
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`border px-3 py-2 text-sm font-medium transition ${
        active
          ? "border-teal-700 bg-teal-700 text-white"
          : "border-neutral-300 bg-white text-neutral-700 hover:border-neutral-500"
      }`}
      onClick={onClick}
      type="button"
    >
      {label}
    </button>
  );
}

function StatusBadge({ status }: { status: ReviewStatus }) {
  const className =
    status === "done"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : status === "error"
        ? "border-red-200 bg-red-50 text-red-800"
        : "border-amber-200 bg-amber-50 text-amber-800";

  return (
    <span className={`inline-flex border px-2 py-1 text-xs font-semibold ${className}`}>
      {status}
    </span>
  );
}

function SeverityBadge({ severity }: { severity: Severity }) {
  const className =
    severity === "Critical"
      ? "border-red-200 bg-red-50 text-red-800"
      : severity === "Major"
        ? "border-amber-200 bg-amber-50 text-amber-900"
        : "border-sky-200 bg-sky-50 text-sky-800";

  return (
    <span className={`border px-2 py-1 ${className}`}>
      {severity}
    </span>
  );
}

function NoteFeedback({
  error,
  state
}: {
  error?: string;
  state: NoteState;
}) {
  if (state === "saved") {
    return <p className="mt-2 text-sm font-medium text-emerald-700">Note saved.</p>;
  }

  if (state === "error") {
    return (
      <p className="mt-2 text-sm font-medium text-red-700">
        {error || "Could not save this note."}
      </p>
    );
  }

  return null;
}

function filterAgencies(
  report: ComplianceReport,
  agencyFilter: AgencyFilter,
  severityFilter: SeverityFilter
): AgencyReview[] {
  return report.agencies
    .filter((agency) => agencyFilter === "all" || agency.agency === agencyFilter)
    .map((agency) => ({
      ...agency,
      issues: agency.issues.filter(
        (issue) => severityFilter === "all" || issue.severity === severityFilter
      )
    }))
    .filter((agency) => agency.issues.length > 0);
}

function draftsFromReview(review: ReviewDetail): Record<string, string> {
  const drafts: Record<string, string> = {};

  for (const agency of review.report?.agencies ?? []) {
    for (const issue of agency.issues) {
      drafts[issue.id] = issue.note;
    }
  }

  return drafts;
}

function updateIssueInReview(
  review: ReviewDetail,
  issueId: string,
  note: string
): ReviewDetail {
  if (!review.report) {
    return review;
  }

  return {
    ...review,
    report: {
      ...review.report,
      agencies: review.report.agencies.map((agency) => ({
        ...agency,
        issues: agency.issues.map((issue) =>
          issue.id === issueId ? { ...issue, note } : issue
        )
      }))
    }
  };
}

function agencyStyle(agency: string) {
  return AGENCY_PALETTE[agency] ?? DEFAULT_AGENCY_STYLE;
}

function agencyCount(report: ComplianceReport, agency: AgencyReview): number {
  return report.summary.by_agency[agency.agency] ?? agency.issues.length;
}

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(date);
}

"use client";

import { type Dispatch, type SetStateAction, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  API_BASE,
  createReview,
  getReview,
  listReviews,
  type AgencyCode,
  type DrawingType,
  type ReviewListItem,
  type ReviewStatus,
  type SubmissionType
} from "@/lib/api";

const AGENCIES: { code: AgencyCode; name: string }[] = [
  { code: "bca", name: "BCA" },
  { code: "scdf", name: "SCDF" },
  { code: "ura", name: "URA" },
  { code: "lta", name: "LTA" },
  { code: "nparks", name: "NParks" },
  { code: "nea", name: "NEA" },
  { code: "pub", name: "PUB" }
];
const DRAWING_TYPES = [
  "Floor Plan",
  "Site Plan",
  "Section & Elevation",
  "Drainage",
  "Fire Safety",
  "Mixed Set"
] as const;
const SUBMISSION_TYPES: SubmissionType[] = ["Design", "Authority Submission"];
const POLL_INTERVAL_MS = 3000;

export function Dashboard() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pollTimeoutRef = useRef<number | null>(null);
  const [drawingType, setDrawingType] = useState<DrawingType>("Mixed Set");
  const [submissionType, setSubmissionType] = useState<SubmissionType>("Design");
  const [selectedAgencies, setSelectedAgencies] = useState<AgencyCode[]>(
    AGENCIES.map((agency) => agency.code)
  );
  const [description, setDescription] = useState("");
  const [reviewNotes, setReviewNotes] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [reviews, setReviews] = useState<ReviewListItem[]>([]);
  const [reviewsLoading, setReviewsLoading] = useState(true);
  const [reviewsError, setReviewsError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [activeReviewId, setActiveReviewId] = useState<string | null>(null);
  const [processingStatus, setProcessingStatus] = useState<string | null>(null);

  const selectedFileLabel = useMemo(() => {
    if (!selectedFile) {
      return "No PDF selected";
    }

    const sizeInMb = selectedFile.size / (1024 * 1024);
    return `${selectedFile.name} (${sizeInMb.toFixed(1)} MB)`;
  }, [selectedFile]);

  const loadReviews = useCallback(async () => {
    setReviewsLoading(true);
    setReviewsError(null);

    try {
      const reviewList = await listReviews();
      setReviews(reviewList);
    } catch (error) {
      setReviewsError(readableError(error));
    } finally {
      setReviewsLoading(false);
    }
  }, []);

  const stopPolling = useCallback(() => {
    if (pollTimeoutRef.current !== null) {
      window.clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
  }, []);

  const pollReview = useCallback(
    async (reviewId: string) => {
      try {
        const review = await getReview(reviewId);

        if (review.status === "done") {
          stopPolling();
          setProcessingStatus("Review complete. Opening the report...");
          router.push(`/reviews/${reviewId}`);
          return;
        }

        if (review.inventory_status === "needs_confirmation") {
          stopPolling();
          setProcessingStatus("Drawing check needs confirmation. Opening the review...");
          router.push(`/reviews/${reviewId}`);
          return;
        }

        if (review.status === "error") {
          stopPolling();
          setActiveReviewId(null);
          setProcessingStatus(null);
          setUploadError(
            review.error_message ||
              "The backend could not complete this review. Check the backend terminal and try again."
          );
          void loadReviews();
          return;
        }

        setProcessingStatus(review.status_message || "Review is processing. This can take a few minutes.");
        pollTimeoutRef.current = window.setTimeout(() => {
          void pollReview(reviewId);
        }, POLL_INTERVAL_MS);
      } catch (error) {
        stopPolling();
        setActiveReviewId(null);
        setProcessingStatus(null);
        setUploadError(readableError(error));
      }
    },
    [loadReviews, router, stopPolling]
  );

  useEffect(() => {
    void loadReviews();

    return () => {
      stopPolling();
    };
  }, [loadReviews, stopPolling]);

  const chooseFile = useCallback((file: File | null) => {
    setUploadError(null);

    if (!file) {
      setSelectedFile(null);
      return;
    }

    if (!isPdf(file)) {
      setSelectedFile(null);
      setUploadError("Please choose a PDF file. Other file types are not supported yet.");
      return;
    }

    setSelectedFile(file);
  }, []);

  const handleUpload = async () => {
    if (!selectedFile || isUploading || activeReviewId || selectedAgencies.length === 0) {
      return;
    }

    setIsUploading(true);
    setUploadError(null);
    setProcessingStatus("Uploading PDF to the local backend...");

    try {
      const response = await createReview({
        file: selectedFile,
        drawingType,
        description,
        reviewNotes,
        selectedAgencies,
        submissionType
      });
      setActiveReviewId(response.review_id);
      setProcessingStatus("Upload received. Starting review...");
      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      void loadReviews();
      void pollReview(response.review_id);
    } catch (error) {
      setProcessingStatus(null);
      setUploadError(readableError(error));
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <main className="min-h-screen bg-neutral-100 text-neutral-950">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-5 py-6 sm:px-8 lg:px-10">
        <header className="flex flex-col justify-between gap-4 border-b border-neutral-300 pb-5 md:flex-row md:items-end">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-teal-700">
              Local compliance workspace
            </p>
            <h1 className="mt-2 text-3xl font-semibold text-neutral-950">
              Compliance Reviewer
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-neutral-600">
              Upload an architecture drawing PDF, run a local multi-agency review,
              and come back to past reports when you need them.
            </p>
          </div>
          <div className="border border-neutral-300 bg-white px-4 py-3 text-sm shadow-sm">
            <p className="font-medium text-neutral-600">Backend API</p>
            <p className="mt-1 font-mono text-xs text-neutral-900">{API_BASE}</p>
          </div>
        </header>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <section className="border border-neutral-300 bg-white p-5 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold">New review</h2>
                <p className="mt-1 text-sm text-neutral-600">
                  Add a little drawing context, then upload the PDF.
                </p>
              </div>
              <span className="border border-teal-200 bg-teal-50 px-2.5 py-1 text-xs font-medium text-teal-800">
                PDF only
              </span>
            </div>

            <fieldset className="mt-5">
              <legend className="text-sm font-medium text-neutral-800">Agencies to review</legend>
              <div className="mt-2 flex flex-wrap gap-2">
                {AGENCIES.map((agency) => {
                  const selected = selectedAgencies.includes(agency.code);

                  return (
                    <label
                      className={`cursor-pointer border px-3 py-2 text-sm font-medium transition ${
                        selected
                          ? "border-teal-700 bg-teal-50 text-teal-900"
                          : "border-neutral-300 bg-white text-neutral-700 hover:border-neutral-500"
                      }`}
                      key={agency.code}
                    >
                      <input
                        checked={selected}
                        className="sr-only"
                        onChange={() => toggleAgency(agency.code, setSelectedAgencies)}
                        type="checkbox"
                      />
                      {agency.name}
                    </label>
                  );
                })}
              </div>
              {selectedAgencies.length === 0 ? (
                <p className="mt-2 text-sm font-medium text-red-700">
                  Choose at least one agency before starting the review.
                </p>
              ) : (
                <p className="mt-2 text-sm text-neutral-600">
                  Selected: {formatAgencyCodes(selectedAgencies)}
                </p>
              )}
            </fieldset>

            <fieldset className="mt-5">
              <legend className="text-sm font-medium text-neutral-800">Submission type</legend>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {SUBMISSION_TYPES.map((type) => (
                  <label
                    className={`cursor-pointer border px-3 py-2 text-sm font-medium transition ${
                      submissionType === type
                        ? "border-teal-700 bg-teal-50 text-teal-900"
                        : "border-neutral-300 bg-white text-neutral-700 hover:border-neutral-500"
                    }`}
                    key={type}
                  >
                    <input
                      checked={submissionType === type}
                      className="sr-only"
                      name="submission-type"
                      onChange={() => setSubmissionType(type)}
                      type="radio"
                    />
                    {type}
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset className="mt-5">
              <legend className="text-sm font-medium text-neutral-800">Drawing type</legend>
              <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                {DRAWING_TYPES.map((type) => (
                  <label
                    className={`cursor-pointer border px-3 py-2 text-sm font-medium transition ${
                      drawingType === type
                        ? "border-teal-700 bg-teal-50 text-teal-900"
                        : "border-neutral-300 bg-white text-neutral-700 hover:border-neutral-500"
                    }`}
                    key={type}
                  >
                    <input
                      checked={drawingType === type}
                      className="sr-only"
                      name="drawing-type"
                      onChange={() => setDrawingType(type)}
                      type="radio"
                    />
                    {type}
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="mt-5 grid gap-4">
              <label className="block">
                <span className="text-sm font-medium text-neutral-800">Short description</span>
                <textarea
                  className="mt-2 min-h-24 w-full resize-y border border-neutral-300 bg-white px-3 py-2 text-sm leading-6 text-neutral-900 outline-none transition placeholder:text-neutral-400 focus:border-teal-700"
                  maxLength={800}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="Example: Three-storey landed house with basement, roof terrace, and side boundary works."
                  value={description}
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-neutral-800">Review notes</span>
                <textarea
                  className="mt-2 min-h-20 w-full resize-y border border-neutral-300 bg-white px-3 py-2 text-sm leading-6 text-neutral-900 outline-none transition placeholder:text-neutral-400 focus:border-teal-700"
                  maxLength={800}
                  onChange={(event) => setReviewNotes(event.target.value)}
                  placeholder="Optional: areas to pay closer attention to, such as drainage reserve, fire access, or URA envelope."
                  value={reviewNotes}
                />
              </label>
            </div>

            <div
              className={`mt-5 flex min-h-52 flex-col items-center justify-center border-2 border-dashed px-5 py-8 text-center transition ${
                dragActive
                  ? "border-teal-600 bg-teal-50"
                  : "border-neutral-300 bg-neutral-50"
              }`}
              onDragEnter={(event) => {
                event.preventDefault();
                setDragActive(true);
              }}
              onDragLeave={(event) => {
                event.preventDefault();
                setDragActive(false);
              }}
              onDragOver={(event) => {
                event.preventDefault();
                setDragActive(true);
              }}
              onDrop={(event) => {
                event.preventDefault();
                setDragActive(false);
                chooseFile(event.dataTransfer.files.item(0));
              }}
            >
              <p className="text-base font-semibold text-neutral-900">
                Drag a drawing PDF here
              </p>
              <p className="mt-2 max-w-sm text-sm leading-6 text-neutral-600">
                Or browse for a file from your Mac. Private PDFs stay in your local
                backend upload folder.
              </p>
              <button
                className="mt-4 border border-neutral-900 bg-neutral-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-neutral-700"
                onClick={() => fileInputRef.current?.click()}
                type="button"
              >
                Choose PDF
              </button>
              <input
                accept="application/pdf,.pdf"
                className="hidden"
                onChange={(event) => chooseFile(event.target.files?.item(0) ?? null)}
                ref={fileInputRef}
                type="file"
              />
              <p className="mt-4 text-sm font-medium text-neutral-800">
                {selectedFileLabel}
              </p>
            </div>

            {uploadError ? (
              <p className="mt-4 border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {uploadError}
              </p>
            ) : null}

            {processingStatus ? (
              <div className="mt-4 border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-900">
                <p className="font-semibold">{processingStatus}</p>
                {activeReviewId ? (
                  <p className="mt-1 font-mono text-xs">Review ID: {activeReviewId}</p>
                ) : null}
              </div>
            ) : null}

            <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-neutral-600">
                {submissionType} - {drawingType} - {selectedAgencies.length}{" "}
                {selectedAgencies.length === 1 ? "agency" : "agencies"}
              </p>
              <button
                className="border border-teal-700 bg-teal-700 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:border-neutral-300 disabled:bg-neutral-300 disabled:text-neutral-600"
                disabled={!selectedFile || selectedAgencies.length === 0 || isUploading || Boolean(activeReviewId)}
                onClick={handleUpload}
                type="button"
              >
                {isUploading ? "Uploading..." : activeReviewId ? "Review running..." : "Start review"}
              </button>
            </div>
          </section>

          <section className="border border-neutral-300 bg-white p-5 shadow-sm">
            <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
              <div>
                <h2 className="text-lg font-semibold">Past reviews</h2>
                <p className="mt-1 text-sm text-neutral-600">
                  Stored locally by the backend SQLite database.
                </p>
              </div>
              <button
                className="border border-neutral-300 px-3 py-2 text-sm font-medium text-neutral-800 transition hover:border-neutral-500"
                onClick={() => void loadReviews()}
                type="button"
              >
                Refresh
              </button>
            </div>

            <div className="mt-5 overflow-hidden border border-neutral-200">
              <div className="hidden grid-cols-[minmax(0,1.4fr)_minmax(0,0.8fr)_110px_110px] gap-3 border-b border-neutral-200 bg-neutral-50 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neutral-500 sm:grid">
                <span>Filename</span>
                <span>Date</span>
                <span>Issues</span>
                <span>Status</span>
              </div>

              {reviewsLoading ? (
                <div className="px-4 py-8 text-sm text-neutral-600">Loading reviews...</div>
              ) : reviewsError ? (
                <div className="px-4 py-8 text-sm text-red-800">{reviewsError}</div>
              ) : reviews.length === 0 ? (
                <div className="px-4 py-8 text-sm text-neutral-600">
                  No reviews yet. Upload a PDF to start the first one.
                </div>
              ) : (
                <ul className="divide-y divide-neutral-200">
                  {reviews.map((review) => (
                    <li key={review.id}>
                      <button
                        className="grid w-full gap-2 px-4 py-3 text-left text-sm transition hover:bg-neutral-50 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,0.8fr)_110px_110px] sm:gap-3"
                        onClick={() => router.push(`/reviews/${review.id}`)}
                        type="button"
                      >
                        <span className="truncate font-medium text-neutral-900">
                          {review.filename}
                          <span className="mt-1 block truncate text-xs font-normal text-neutral-500">
                            {review.submission_type} - {review.drawing_type} -{" "}
                            {formatAgencyCodes(review.selected_agencies)}
                            {review.status === "processing" && review.status_message
                              ? ` - ${review.status_message}`
                              : ""}
                          </span>
                        </span>
                        <span className="text-neutral-600">
                          {formatDate(review.created_at)}
                        </span>
                        <span className="font-medium text-neutral-800">
                          {review.total_issues}
                        </span>
                        <span>
                          <StatusBadge status={review.status} />
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </div>
      </div>
    </main>
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
    <span className={`inline-flex px-2 py-1 text-xs font-semibold ${className}`}>
      {status}
    </span>
  );
}

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

function toggleAgency(
  agencyCode: AgencyCode,
  setSelectedAgencies: Dispatch<SetStateAction<AgencyCode[]>>
) {
  setSelectedAgencies((current) => {
    if (current.includes(agencyCode)) {
      return current.filter((code) => code !== agencyCode);
    }
    return AGENCIES.map((agency) => agency.code).filter(
      (code) => current.includes(code) || code === agencyCode
    );
  });
}

function formatAgencyCodes(agencyCodes: AgencyCode[]): string {
  if (agencyCodes.length === 0) {
    return "No agencies";
  }

  return agencyCodes
    .map((code) => AGENCIES.find((agency) => agency.code === code)?.name ?? code.toUpperCase())
    .join(", ");
}

function readableError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return "Something went wrong. Check that the local backend server is running.";
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

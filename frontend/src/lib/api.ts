export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8000";

export type ReviewStatus = "processing" | "done" | "error";
export type Severity = "Critical" | "Major" | "Advisory";

export type ReviewListItem = {
  id: string;
  filename: string;
  created_at: string;
  total_issues: number;
  status: ReviewStatus;
};

export type CreateReviewResponse = {
  review_id: string;
};

export type ParsedDocument = {
  filename: string;
  page_count: number;
};

export type ComplianceIssue = {
  id: string;
  title: string;
  severity: Severity;
  description: string;
  clause_reference: string;
  drawing_location: string;
  suggested_resolution: string;
  note: string;
};

export type AgencyReview = {
  agency: string;
  issues: ComplianceIssue[];
};

export type ReviewSummary = {
  total_issues: number;
  by_agency: Record<string, number>;
  by_severity: Partial<Record<Severity, number>>;
};

export type ComplianceReport = {
  document: ParsedDocument;
  reviewed_at: string;
  agencies: AgencyReview[];
  summary: ReviewSummary;
};

export type ReviewDetail = {
  id: string;
  filename: string;
  created_at: string;
  updated_at: string;
  status: ReviewStatus;
  total_issues: number;
  report: ComplianceReport | null;
  error_message: string | null;
};

export type IssueNoteResponse = {
  id: string;
  note: string;
};

export async function listReviews(): Promise<ReviewListItem[]> {
  return request<ReviewListItem[]>("/api/reviews");
}

export async function createReview(file: File): Promise<CreateReviewResponse> {
  const body = new FormData();
  body.append("file", file);

  return request<CreateReviewResponse>("/api/reviews", {
    method: "POST",
    body
  });
}

export async function getReview(reviewId: string): Promise<ReviewDetail> {
  return request<ReviewDetail>(`/api/reviews/${reviewId}`);
}

export function getReviewExportUrl(reviewId: string): string {
  return `${API_BASE}/api/reviews/${encodeURIComponent(reviewId)}/export.pdf`;
}

export async function updateIssueNote(
  issueId: string,
  note: string
): Promise<IssueNoteResponse> {
  return request<IssueNoteResponse>(`/api/issues/${issueId}/note`, {
    method: "PATCH",
    body: JSON.stringify({ note }),
    headers: {
      "Content-Type": "application/json"
    }
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...init
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}.`;

    try {
      const data = (await response.json()) as { detail?: string };
      if (data.detail) {
        message = data.detail;
      }
    } catch {
      // Keep the generic message if the backend did not send JSON.
    }

    throw new Error(message);
  }

  return (await response.json()) as T;
}

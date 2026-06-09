export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8000";

export type ReviewStatus = "processing" | "done" | "error";
export type InventoryStatus = "pending" | "needs_confirmation" | "confirmed" | "error";
export type Severity = "Critical" | "Major" | "Advisory";
export type AgencyCode = "bca" | "scdf" | "ura" | "lta" | "nparks" | "nea" | "pub";
export type SubmissionType = "Design" | "Authority Submission";
export type DrawingViewType =
  | "Floor Plan"
  | "Site Plan"
  | "Section"
  | "Elevation"
  | "Section & Elevation"
  | "Detail"
  | "Schedule/General"
  | "Unknown";

export type ReviewListItem = {
  id: string;
  filename: string;
  created_at: string;
  drawing_type: DrawingType;
  description: string;
  review_notes: string;
  selected_agencies: AgencyCode[];
  submission_type: SubmissionType;
  status_message: string;
  inventory_status: InventoryStatus;
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

export type DrawingType =
  | "Floor Plan"
  | "Site Plan"
  | "Section & Elevation"
  | "Drainage"
  | "Fire Safety"
  | "Mixed Set";

export type IssueMarkup = {
  page_number: number;
  marker_label: string;
  marker_x: number;
  marker_y: number;
};

export type DrawingInventoryItem = {
  page_number: number;
  sheet_title: string;
  drawing_number: string;
  primary_view_type: DrawingViewType;
  detected_view_types: DrawingViewType[];
  confidence: number;
  evidence_labels: string[];
  warnings: string[];
};

export type DrawingInventory = {
  pages: DrawingInventoryItem[];
};

export type ComplianceIssue = {
  id: string;
  title: string;
  severity: Severity;
  description: string;
  clause_reference: string;
  drawing_location: string;
  drawing_page_number: number | null;
  drawing_view_type: DrawingViewType | null;
  suggested_resolution: string;
  note: string;
  markup: IssueMarkup | null;
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
  drawing_type: DrawingType;
  description: string;
  review_notes: string;
  selected_agencies: AgencyCode[];
  submission_type: SubmissionType;
  status_message: string;
  inventory_status: InventoryStatus;
  drawing_inventory: DrawingInventory | null;
  inventory_confirmed_at: string | null;
  inventory_confirmed_by: string | null;
  total_issues: number;
  report: ComplianceReport | null;
  error_message: string | null;
};

export type ReviewInventoryResponse = {
  review_id: string;
  inventory_status: InventoryStatus;
  drawing_inventory: DrawingInventory | null;
  inventory_confirmed_at: string | null;
  inventory_confirmed_by: string | null;
};

export type IssueNoteResponse = {
  id: string;
  note: string;
};

export async function listReviews(): Promise<ReviewListItem[]> {
  return request<ReviewListItem[]>("/api/reviews");
}

export type CreateReviewInput = {
  file: File;
  drawingType: DrawingType;
  description: string;
  reviewNotes: string;
  selectedAgencies: AgencyCode[];
  submissionType: SubmissionType;
};

export async function createReview(input: CreateReviewInput): Promise<CreateReviewResponse> {
  const body = new FormData();
  body.append("file", input.file);
  body.append("drawing_type", input.drawingType);
  body.append("description", input.description);
  body.append("review_notes", input.reviewNotes);
  body.append("submission_type", input.submissionType);
  for (const agencyCode of input.selectedAgencies) {
    body.append("agency_codes", agencyCode);
  }

  return request<CreateReviewResponse>("/api/reviews", {
    method: "POST",
    body
  });
}

export async function getReview(reviewId: string): Promise<ReviewDetail> {
  return request<ReviewDetail>(`/api/reviews/${reviewId}`);
}

export async function getReviewInventory(reviewId: string): Promise<ReviewInventoryResponse> {
  return request<ReviewInventoryResponse>(`/api/reviews/${reviewId}/inventory`);
}

export async function confirmReviewInventory(
  reviewId: string,
  inventory: DrawingInventory
): Promise<ReviewInventoryResponse> {
  return request<ReviewInventoryResponse>(`/api/reviews/${reviewId}/inventory`, {
    method: "PATCH",
    body: JSON.stringify(inventory),
    headers: {
      "Content-Type": "application/json"
    }
  });
}

export function getReviewExportUrl(reviewId: string): string {
  return `${API_BASE}/api/reviews/${encodeURIComponent(reviewId)}/export.pdf`;
}

export function getReviewFileUrl(reviewId: string): string {
  return `${API_BASE}/api/reviews/${encodeURIComponent(reviewId)}/file`;
}

export function getReviewPageImageUrl(reviewId: string, pageNumber: number): string {
  return `${API_BASE}/api/reviews/${encodeURIComponent(reviewId)}/pages/${pageNumber}.png`;
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

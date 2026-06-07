import { ReviewReport } from "@/components/ReviewReport";

type ReviewPageProps = {
  params: {
    id: string;
  };
};

export default function ReviewPage({ params }: ReviewPageProps) {
  return <ReviewReport reviewId={params.id} />;
}

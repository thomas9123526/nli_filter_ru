import { Suspense } from "react";
import { ReviewView } from "@/components/ReviewView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <ReviewView />
    </Suspense>
  );
}

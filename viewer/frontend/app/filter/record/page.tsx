import { Suspense } from "react";
import { RecordView } from "@/components/RecordView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <RecordView />
    </Suspense>
  );
}

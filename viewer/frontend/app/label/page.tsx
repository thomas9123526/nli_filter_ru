import { Suspense } from "react";
import { LabelsView } from "@/components/LabelsView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <LabelsView />
    </Suspense>
  );
}

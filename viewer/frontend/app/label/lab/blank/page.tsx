import { Suspense } from "react";
import { LabView } from "@/components/LabView";
import { Loading } from "@/components/ui";

// /label/lab/blank/: the Experiment page with no run line: one empty text box and a policy picker
export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <LabView blank />
    </Suspense>
  );
}

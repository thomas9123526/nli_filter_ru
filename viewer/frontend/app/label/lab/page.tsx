import { Suspense } from "react";
import { LabView } from "@/components/LabView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <LabView />
    </Suspense>
  );
}

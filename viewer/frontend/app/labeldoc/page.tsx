import { Suspense } from "react";
import { LabelDocView } from "@/components/LabelDocView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <LabelDocView />
    </Suspense>
  );
}

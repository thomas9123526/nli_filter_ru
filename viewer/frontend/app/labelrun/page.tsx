import { Suspense } from "react";
import { LabelRunView } from "@/components/LabelRunView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <LabelRunView />
    </Suspense>
  );
}

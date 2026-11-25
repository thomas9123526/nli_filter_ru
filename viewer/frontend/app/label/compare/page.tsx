import { Suspense } from "react";
import { CompareView } from "@/components/CompareView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <CompareView />
    </Suspense>
  );
}

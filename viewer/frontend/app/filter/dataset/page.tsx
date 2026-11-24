import { Suspense } from "react";
import { DatasetView } from "@/components/DatasetView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <DatasetView />
    </Suspense>
  );
}

import { Suspense } from "react";
import { TuneView } from "@/components/TuneView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <TuneView />
    </Suspense>
  );
}

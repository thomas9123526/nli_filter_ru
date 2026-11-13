import { Suspense } from "react";
import { RunView } from "@/components/RunView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <RunView />
    </Suspense>
  );
}

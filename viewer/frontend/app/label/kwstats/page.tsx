import { Suspense } from "react";
import { KwstatsView } from "@/components/KwstatsView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <KwstatsView />
    </Suspense>
  );
}

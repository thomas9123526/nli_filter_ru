import { Suspense } from "react";
import { CorpusView } from "@/components/CorpusView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <CorpusView />
    </Suspense>
  );
}

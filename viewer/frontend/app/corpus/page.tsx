// Old URL: /corpus/?ds=… forwards to /label/corpus/ (a labelling dataset) or /filter/corpus/ (an nli_filter one).
import { Suspense } from "react";
import { CorpusForward } from "@/components/Forward";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <CorpusForward />
    </Suspense>
  );
}

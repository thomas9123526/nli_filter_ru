import { Suspense } from "react";
import { KeywordsView } from "@/components/KeywordsView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <KeywordsView />
    </Suspense>
  );
}

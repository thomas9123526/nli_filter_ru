import { Suspense } from "react";
import { ExpectedRulesView } from "@/components/ExpectedRulesView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <ExpectedRulesView />
    </Suspense>
  );
}

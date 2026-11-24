import { Suspense } from "react";
import { PolicyEditView } from "@/components/PolicyEditView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <PolicyEditView />
    </Suspense>
  );
}

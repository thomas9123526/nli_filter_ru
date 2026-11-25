import { Suspense } from "react";
import { DocsEditView } from "@/components/DocsEditView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <DocsEditView />
    </Suspense>
  );
}

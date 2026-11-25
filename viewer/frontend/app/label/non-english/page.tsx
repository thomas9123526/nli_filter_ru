import { Suspense } from "react";
import { NonEnglishEditView } from "@/components/ConfigEditors";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <NonEnglishEditView />
    </Suspense>
  );
}

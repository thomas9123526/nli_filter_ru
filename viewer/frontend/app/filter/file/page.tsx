import { Suspense } from "react";
import { FileView } from "@/components/FileView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <FileView />
    </Suspense>
  );
}

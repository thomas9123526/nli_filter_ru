import { Suspense } from "react";
import { ListFilesView } from "@/components/ListFilesView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <ListFilesView />
    </Suspense>
  );
}

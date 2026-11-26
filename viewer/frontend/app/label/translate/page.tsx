import { Suspense } from "react";
import { TranslateSettingsView } from "@/components/TranslateSettingsView";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <TranslateSettingsView />
    </Suspense>
  );
}

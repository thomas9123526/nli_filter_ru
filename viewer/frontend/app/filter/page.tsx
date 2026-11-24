"use client";
// The Filter area's home: nli_filter.py outputs and the corpus they were made from.
import { DatasetList } from "@/components/DatasetList";
import { Crumbs } from "@/components/ui";

export default function FilterHome() {
  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Filter" }]} />
          <h1>Filter datasets</h1>
          <div className="sub">An nli_filter.py output folder and the corpus it was made from. Pick one to browse its decisions.</div>
        </div>
      </div>
      <DatasetList kind="filter" />
    </>
  );
}

// Old URL: forwards to the new one (query string kept), so bookmarks and links in cmds/ still work.
import { Forward } from "@/components/Forward";

export default function Page() {
  return <Forward to="/label/" />;
}

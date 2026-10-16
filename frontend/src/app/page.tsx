import { UnderwritingDashboard } from "@/components/UnderwritingDashboard";

/** The underwriting console is entirely interactive, so the page is a thin
 *  server component that hands off to the client dashboard. */
export default function Home() {
  return <UnderwritingDashboard />;
}

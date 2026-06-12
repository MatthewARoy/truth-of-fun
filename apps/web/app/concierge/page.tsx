import { redirect } from "next/navigation";

// The planner UI superseded this page; keep the old URL working.
export default function ConciergePage() {
  redirect("/planner");
}

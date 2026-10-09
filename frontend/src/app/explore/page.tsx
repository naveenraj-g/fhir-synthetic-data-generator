import type { Metadata } from "next";
import { Explorer } from "@/components/explore/explorer";

export const metadata: Metadata = { title: "Find codes" };

export default function ExplorePage() {
  return <Explorer />;
}

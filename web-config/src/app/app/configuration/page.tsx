import { Suspense } from "react";
import { redirect } from "next/navigation";
import { BrokerConfiguration } from "@/components/broker-configuration";
export default async function ConfigurationPage({
  searchParams,
}: {
  searchParams: Promise<{ firm?: string }>;
}) {
  if (!(await searchParams).firm) redirect("/app/following");
  return (
    <Suspense fallback={<div className="page-wrap">Loading configuration…</div>}>
      <BrokerConfiguration />
    </Suspense>
  );
}

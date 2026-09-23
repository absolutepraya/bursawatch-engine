import { NextResponse } from "next/server";

import { getWorkspaceRecords } from "@/lib/sample-workspace";

export const runtime = "nodejs";

export function GET() {
  return NextResponse.json({ sources: getWorkspaceRecords().listSources() });
}

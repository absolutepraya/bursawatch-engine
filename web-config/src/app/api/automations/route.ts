import { NextResponse } from "next/server";
import { getWorkspaceRecords } from "@/lib/sample-workspace";

export function GET() {
  return NextResponse.json({ automations: getWorkspaceRecords().listAutomations() });
}

export function POST() {
  return NextResponse.json({ error: "Watches are saved in your browser. Backend configuration is not connected." }, { status: 403 });
}

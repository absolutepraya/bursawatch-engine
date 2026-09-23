import { NextResponse } from "next/server";

export function PATCH() {
  return NextResponse.json({ error: "Sample records are read-only. Create a watch to save preferences in this browser." }, { status: 403 });
}

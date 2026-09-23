import { handleControlRequest } from "@/server/control-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
type Context = { params: Promise<{ path: string[] }> };
async function handle(request: Request, context: Context) {
  const { path } = await context.params;
  return handleControlRequest(request, path, { origin: process.env.CONTROL_PLANE_API_URL ?? process.env.NEXT_PUBLIC_CONTROL_PLANE_API_URL ?? "" });
}
export const GET = handle;
export const PUT = handle;
export const POST = handle;

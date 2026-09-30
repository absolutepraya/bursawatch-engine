import "server-only";
import { z } from "zod";
import { catalogWrite } from "@/lib/source-catalog";
import {
  avatarInput,
  ControlPlaneError,
  createControlPlaneReader,
  scheduleInput,
} from "@/server/control-plane";

const opaqueId = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/;
const headers = {
  "Cache-Control": "private, no-store, max-age=0",
  Vary: "Authorization",
  "X-Content-Type-Options": "nosniff",
};
const configWrite = z
  .object({
    expectedRevision: z.number().int().positive(),
    config_version: z.number().int().positive(),
    config: z.record(z.string(), z.unknown()),
  })
  .strict();
const scheduleWrite = scheduleInput
  .extend({ expectedRevision: z.number().int().positive() })
  .strict();

export async function handleControlRequest(
  request: Request,
  path: string[],
  options: { origin: string; fetchImpl?: typeof fetch },
) {
  const json = (body: unknown, status = 200) => Response.json(body, { status, headers });
  const authorization = request.headers.get("authorization") ?? "";
  // Only user-JWT-shaped credentials are forwarded. The upstream validates
  // signature, issuer, role and admin membership on every operation.
  const token = /^Bearer ([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)$/.exec(
    authorization,
  )?.[1];
  if (!token || token.length > 16384)
    return json({ code: "auth", message: "Sign in to view the workspace." }, 401);
  if (path.some((part) => !opaqueId.test(part)))
    return json({ code: "missing", message: "Page not found." }, 404);
  if (!["GET", "PUT", "POST"].includes(request.method))
    return json({ code: "forbidden", message: "This operation is not available." }, 405);
  if (request.method !== "GET" && request.headers.get("origin") !== new URL(request.url).origin)
    return json(
      { code: "forbidden", message: "Open this form in your Bursawatch workspace." },
      403,
    );
  try {
    const api = createControlPlaneReader({
      origin: options.origin,
      getAccessToken: async () => token,
      fetchImpl: options.fetchImpl,
    });
    if (request.method === "GET") {
      if (path.length === 1 && path[0] === "source-catalog")
        return json(await api.getSourceCatalog());
      if (path.length === 2 && path[0] === "source-catalog" && path[1] === "effective")
        return json(await api.getEffectiveCatalog());
      if (path.length === 1 && path[0] === "watchers") return json(await api.listWatchers());
      if (path.length === 1 && path[0] === "components") return json(await api.listComponents());
      if (path.length === 2 && path[0] === "components")
        return json(await api.getComponent(path[1]));
      if (path.length === 3 && path[0] === "components" && path[2] === "activity")
        return json(await api.getComponentActivity(path[1]));
      if (path.length === 1 && path[0] === "jobs") return json(await api.listOperatorJobs());
      if (path.length === 2 && path[0] === "jobs") return json(await api.getOperatorJob(path[1]));
      if (path.length === 1 && path[0] === "observations")
        return json(await api.listObservations());
      if (path.length === 3 && path[0] === "watchers") {
        if (path[2] === "jobs") return json(await api.listJobs(path[1]));
        if (path[2] === "runs") return json(await api.listRuns(path[1]));
        if (path[2] === "config") return json(await api.getConfig(path[1]));
        if (path[2] === "profiles") return json(await api.listProfiles(path[1]));
      }
      if (path.length === 3 && path[0] === "jobs" && path[2] === "schedule")
        return json(await api.getSchedule(path[1]));
      if (path.length === 3 && path[0] === "runs" && path[2] === "events")
        return json(await api.listRunEvents(path[1]));
    } else {
      const isCatalog =
        request.method === "PUT" &&
        path.length === 2 &&
        path[0] === "source-catalog" &&
        path[1] === "config";
      const isConfig =
        request.method === "PUT" &&
        path.length === 3 &&
        path[0] === "watchers" &&
        path[2] === "config";
      const isSchedule =
        request.method === "PUT" &&
        path.length === 3 &&
        path[0] === "jobs" &&
        path[2] === "schedule";
      const isAvatar =
        request.method === "PUT" &&
        path.length === 5 &&
        path[0] === "watchers" &&
        path[2] === "profiles" &&
        path[4] === "avatar";
      const isRefresh =
        request.method === "POST" &&
        path.length === 6 &&
        path[0] === "watchers" &&
        path[2] === "profiles" &&
        path[4] === "avatar" &&
        path[5] === "refresh";
      if (!isCatalog && !isConfig && !isSchedule && !isAvatar && !isRefresh)
        return json({ code: "missing", message: "Page not found." }, 404);
      if (!request.headers.get("content-type")?.startsWith("application/json"))
        throw new ControlPlaneError("validation");
      const stream = request.body?.getReader();
      if (!stream) throw new ControlPlaneError("validation");
      let bytes = 0;
      const chunks: Uint8Array[] = [];
      try {
        while (true) {
          const { done, value } = await stream.read();
          if (done) break;
          bytes += value.byteLength;
          if (bytes > 256 * 1024) {
            await stream.cancel();
            throw new ControlPlaneError("validation");
          }
          chunks.push(value);
        }
      } finally {
        stream.releaseLock();
      }
      let input: unknown;
      try {
        input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      } catch {
        throw new ControlPlaneError("validation");
      }
      if (isCatalog) {
        const parsed = catalogWrite.safeParse(input);
        if (!parsed.success) throw new ControlPlaneError("validation");
        return json(await api.saveSourceCatalog(parsed.data.expected_revision, parsed.data.config));
      }
      if (isAvatar) {
        const parsed = avatarInput.safeParse(input);
        if (!parsed.success) throw new ControlPlaneError("validation");
        return json(await api.saveProfileAvatar(path[1], path[3], parsed.data));
      }
      if (isRefresh) {
        if (!z.object({}).strict().safeParse(input).success)
          throw new ControlPlaneError("validation");
        return json(await api.refreshProfileAvatar(path[1], path[3]));
      }
      if (isConfig) {
        const parsed = configWrite.safeParse(input);
        if (!parsed.success) throw new ControlPlaneError("validation");
        const { expectedRevision, ...payload } = parsed.data;
        return json(await api.saveConfig(path[1], expectedRevision, payload));
      }
      const parsed = scheduleWrite.safeParse(input);
      if (!parsed.success) throw new ControlPlaneError("validation");
      const { expectedRevision, ...payload } = parsed.data;
      return json(await api.saveSchedule(path[1], expectedRevision, payload));
    }
    return json({ code: "missing", message: "Page not found." }, 404);
  } catch (error) {
    if (error instanceof ControlPlaneError) {
      const statuses = {
        setup: 503,
        auth: 401,
        forbidden: 403,
        missing: 404,
        "rate-limit": 429,
        unavailable: 503,
        "invalid-response": 502,
        validation: 422,
        conflict: 409,
        "unknown-outcome": 502,
      };
      return json(
        { code: error.code, message: error.message, fields: error.fields },
        statuses[error.code],
      );
    }
    return json(
      { code: "unavailable", message: "The workspace could not complete this request. Try again." },
      503,
    );
  }
}

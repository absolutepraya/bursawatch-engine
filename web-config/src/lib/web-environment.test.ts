import { describe, expect, it } from "vitest";
import { publicAuthSettings } from "./web-environment";
const env = {
  NEXT_PUBLIC_SUPABASE_URL: "https://auth.example.test",
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_example_only",
};
describe("public authentication configuration", () => {
  it("returns only a public key and canonical origin", () => {
    expect(publicAuthSettings({ ...env, PRIVATE_DATABASE_PASSWORD: "never-export" })).toEqual({
      supabaseUrl: env.NEXT_PUBLIC_SUPABASE_URL,
      publishableKey: env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
    });
  });
  it.each(["sb_secret_do_not_expose", "database-password", "", "a.b.c"])(
    "rejects non-public credentials: %s",
    (key) => {
      expect(publicAuthSettings({ ...env, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: key })).toBeNull();
    },
  );
  it.each([
    "http://auth.example.test",
    "https://user:pass@auth.example.test",
    "https://auth.example.test/path",
    "https://auth.example.test?token=x",
    "https://auth.example.test#x",
  ])("rejects ambiguous endpoints: %s", (url) => {
    expect(publicAuthSettings({ ...env, NEXT_PUBLIC_SUPABASE_URL: url })).toBeNull();
  });
  it("accepts a legacy anon key but never a service-role key", () => {
    const key = (role: string) =>
      `e30.${Buffer.from(JSON.stringify({ role })).toString("base64url")}.signature`;
    expect(
      publicAuthSettings({ ...env, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: key("anon") }),
    ).not.toBeNull();
    expect(
      publicAuthSettings({ ...env, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: key("service_role") }),
    ).toBeNull();
    expect(publicAuthSettings({})).toBeNull();
  });
});

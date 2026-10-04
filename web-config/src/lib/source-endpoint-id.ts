import { z } from "zod";

// Catalog endpoint IDs are opaque and case-sensitive. System-owned identities
// include platform namespaces, dotted handles and mixed-case channel IDs.
// This is separate from the narrower component, job and user-created ID rules.
export const sourceEndpointId = z
  .string()
  .regex(/^[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}$/)
  // Reject trailing line terminators that JavaScript's $ anchor permits.
  .refine((value) => value === value.trim());

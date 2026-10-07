# Morning brief feasibility handoff

Status: agreed behavior and bounded feasibility evidence, not an implementation plan or production approval. Latest evidence: 5 October 2026. See the [design spec](2026-09-27-bursawatch-morning-brief-design-spec.md) and [validation record](2026-10-05-morning-brief-feasibility-validation.md).

## Verified and open boundaries

| Area | Verified | Remaining work |
| --- | --- | --- |
| Equity prices | 962 distinct positive closes for 2 October, all 188 conglomerate members included | Initialize aligned session history; verify member eligibility and repeated daily coverage |
| Cap snapshots | Five credits collect positive caps for all 962 stocks, all 11 sectors and 34 groups | Use collection time with underlying effective date unverified; retain per-refresh coverage checks |
| Corporate actions | DSSA historical bulk/daily closes match before and after its verified split | Exclude unhandled events; avoid double adjustment; no universal provider contract inferred |
| Budget | 1,000 monthly operating credits and separate 600-credit history ceiling agreed | Implement shared reservations, resumable pagination and bounded retries; dashboard remains account authority |
| Calendar | Indexed official October schedule supports 2 October as previous session | Obtain retained authoritative calendar and check amendments; never replace it with weekdays alone |
| Chart | Shared layout/key render private 800 by 600 PNG without cookies | Public layout still differs from user-confirmed saved settings; finalize profile and freshness verification |
| Source evidence | Existing envelopes retain text, timestamps, URLs and immutable versions | Add a bounded read surface and consistent frozen manifest; verify retained live corpus separately |
| Attribution | Available canonical publisher metadata accepted | Deduplicate copies, keep unknown origin in provenance, share three-item cap across lanes |
| Delivery | Individual immutable operations, receipt lookup and uncertain-create reconciliation exist | Morning publication manifest, prerequisite gating and service-owned deadline support are new work |
| Permissions | Public product demonstration is required by hackathon rules | Account-specific cache/derived-output permission and Chart-IMG terms conflict need clarification |
| Competition | Eligible-period repository and no prior-project work requirements confirmed | Complete onboarding before coding; keep eligible entry separate from older Hermes work |

## Required delivery design extension

Current local main 9102eaf has no per-operation expiry/cancellation field. Accepted pending/retrying operations may continue after 08:15. The morning owner cannot enforce the agreed cutoff merely by ceasing submissions. Retaining that behavior therefore requires an optional delivery-attempt deadline carried through the shared client, validated API intent, immutable digest, durable store and worker. This is a required future design capability, not an implemented or approved service rollout.

The user confirmed retaining the cutoff and including this deadline capability in future implementation. The submission-only cutoff alternative is not adopted.

For morning creates, stop initiating new send attempts after 08:15 WIB. A request started before expiry can have an uncertain result afterward; continue bounded read-only reconciliation and retain its receipt without issuing a blind replacement create. Deadline expiry must not erase accepted identity, attachments, attempts or ambiguity. Other consumers need not supply a morning deadline. Exact terminal receipt schema and compatibility handling belong to later implementation design.

The common ordering key preserves accepted queue order, but a rejected predecessor can unblock later operations. Queue order alone does not establish publication prerequisites. The morning owner must inspect matching terminal receipts before advancing dependent steps, distinguish explicitly omitted unavailable images from delivery rejection, and preserve the available-text policy. Pending or ambiguous creates cannot be treated as omitted. A rejected text anchor cannot silently produce an orphan image. The six-step manifest is not an atomic transaction.

The service accepts attachment bytes and durably stages them internally, validating hashes on reload. It has no separate caller-facing media-ref staging API and no verified automatic media TTL. Retain frozen caller bytes until acceptance; choose an explicit retention policy without inventing an existing API. The shared ten-second receipt wait is a polling window after an initial status request, not a ten-second total wall-clock guarantee.

## No-post acceptance cases for future implementation

- Align exactly 18 verified closing levels per eligible member and IHSG for the five 10/3 observations. Ignore provider rows on exchange holidays; do not fill missing session prices with old closes silently.
- Confirm positive caps, consistent member eligibility, the 90-percent original-cap floor, normalized weights and fixed-membership provenance. Check the independent formula, not proprietary RRG equivalence.
- Exercise history pagination where totals/order differ by date; reuse valid checkpoints and respect credit reservations through interruption and 429 cooldown.
- Use the DSSA fixture to detect double adjustment; quarantine action cases whose price units cannot be reconciled.
- Freeze source versions in one consistent snapshot; test late commits, corrections and tombstones, overflow, weekend/holiday lookback and missing retained evidence. Keep available publisher identities and cross-source dedup separate.
- Select generated or facts-only fallback by 07:55 from frozen 07:30 evidence. Weak outlook evidence yields facts-only text; missing images do not invent replacement data.
- Freeze accepted text/image bytes and operation keys across restart. Advance dependent steps only from matching receipts or explicit omission policy, never acceptance alone.
- Simulate lost submission responses, crashes after accepted creates, rejection, staged-byte corruption and inconclusive reconciliation. Reuse durable identities and never blindly duplicate creates.
- Exercise the 08:15 deadline before acceptance, during retry and during ambiguous read-back. Do not initiate expired sends; preserve receipts and reconciliation for earlier attempts.
- Use fake transports, isolated temporary stores and disabled posting paths. No production messages, scheduler triggers, service restarts or runtime writes are part of this checklist.

No new clients, endpoint, database, cron, tests, deployment, provider message or full history fetch was introduced by this handoff.

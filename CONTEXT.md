# Hermes Job Watcher

This context defines the language for the job-watcher migration and its posting-selection policy.

## Language

**Job Watcher**:
The scheduled job-discovery workflow that searches job boards, filters and deduplicates postings, then delivers new matches to Discord.
_Avoid_: Career-Ops scanner, job finder cron

**Eligible Posting**:
A posting that may be delivered to Discord after it satisfies role, seniority, and location policy. Eligibility is intentionally permissive when work location or work schema is missing.
_Avoid_: confirmed fit, approved application

**Workmode**:
The posting's declared working arrangement: onsite, remote, or unknown. Workmode is distinct from the country named in its location field.
_Avoid_: location, geography

**Location Policy**:
The delivery rule that accepts Indonesia onsite roles, remote roles from any location including Indonesia, and postings with unknown workmode or location. It rejects explicitly onsite roles outside Indonesia.
_Avoid_: visa policy, application eligibility

**Product Engineering**:
The full-time engineering target comprising Product Engineer, Full-stack Engineer, Software Engineer, Software Developer, and Founding Engineer roles. It excludes Product Manager roles.
_Avoid_: product management, generic product roles

**AI Engineering**:
The full-time production-AI target comprising AI Engineer, Machine Learning Engineer, ML Engineer, LLM Engineer, Generative AI Engineer, Applied AI Engineer, MLOps, and LLMOps roles. It excludes research-first roles such as Research Scientist.
_Avoid_: AI research track, data-science-only role

**Full-time Seniority Policy**:
The title policy that accepts entry-level, associate, junior, unspecific, and Staff roles for the full-time target. Staff is included even when title conventions vary between markets.
_Avoid_: intern-only filter, automatic Staff exclusion

**Gateway-independent Watchdog**:
A system-crontab liveness check that is deliberately outside Hermes scheduling so it can alert when the Hermes gateway or scheduler is unavailable.
_Avoid_: duplicate watcher, backup cron

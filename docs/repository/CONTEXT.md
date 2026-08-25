# Hermes Repository

This context defines the language for versioned Hermes development source and its boundary from operational data and backup snapshots.

## Language

**Hermes Development Repository**:
The private versioned home for reviewed Hermes development sources. It excludes live runtime data and machine backup snapshots.
_Avoid_: Hermes runtime, dotfiles mirror, backup repository

**Cobalt Project**:
The Hermes-owned development source for Yanto's social-media extraction service. It belongs inside the Hermes Development Repository rather than being versioned as an independent repository.
_Avoid_: Cobalt nested repository, Cobalt submodule

**Dotfiles Snapshot**:
A scrubbed backup of machine configuration and selected VPS runtime material. It does not own development sources already tracked by the Hermes Development Repository.
_Avoid_: development repository, source mirror

**Published Commit**:
A clean Hermes Development Repository commit that is reachable from its configured GitHub remote. Only Published Commits are eligible for deployment to the VPS.
_Avoid_: local-only commit, dirty source, deployment snapshot

**Validation Workflow**:
A read-only GitHub workflow that tests and checks repository changes without credentials or deployment authority. It never changes the VPS or any external runtime.
_Avoid_: deployment pipeline, CD workflow, automatic deployment

**Manual Deployment**:
An explicitly invoked transfer of a Published Commit's reviewed source to its VPS runtime target. It is never triggered by a GitHub push or Validation Workflow.
_Avoid_: automatic deployment, GitHub deployment

# X Post Watch

`x-post-watch` is the local source for the VPS runtime at `~/.agents/skills/x-post-watch/`.

For the complete new-profile guide, configuration schema, delivery modes, LLM contract, and safe deployment loop, read [PROFILE_CONFIGURATION.md](PROFILE_CONFIGURATION.md).

Run tests from this directory:

```bash
../.venv/bin/python -m pytest -q
```

Deploy executable files with `./deploy.sh x-post-watch`. Then synchronize `SKILL.md`, `README.md`, `SPEC.md`, `CONTEXT.md`, `PROFILE_CONFIGURATION.md`, and `config/watches.json` separately, compare local and VPS SHA-256 hashes, and run the VPS no-post command before registering or changing the scheduler.

Never edit live `state/` or `~/.dotfiles/vps/agents/skills/x-post-watch/`. Add profiles by reviewing `config/watches.json`; first observation records a cursor and never backfills. `discord_channels` declaratively lists destinations, while `enable_llm_title`, `enable_llm_summary`, `enable_llm_routing`, and `enable_llm_relevance_filter` independently control bounded Hermes analysis. `additional_prompt_instruction` is an optional bounded per-profile refinement for a durable writer-specific pattern. `thread_handling.self_chain` collects a four-hour, ten-post same-author chain and waits for its configured quiet window after observation and every new continuation; `disabled` sends each eligible post immediately. The agent evaluates the combined thread, without being overly strict about short contextual continuations. An irrelevant decision is discarded without delivery, while a relevant one returns only the requested source-grounded Indonesian fields through the scanner's validated `submit-analysis` command. Direct ticker disclosures, earnings, corporate actions, dilution, rights issues, private placements, and `#RangkumKeterbukaanInformasi` / `#RangkumReport` posts are deterministically always relevant, so an LLM false decision cannot discard them. The scanner validates a configured route key and owns final Discord delivery. Stock-route headings start with their exchange ticker, and summaries state the analysis directly rather than narrating Ricky's post. Thread media is delivered root-to-latest, then external quote media. RSSHub owns X authentication on the VPS. HTTP 401 or 403 means authentication trouble, but credentials must never appear in output.

# Shared ordinary-news classification

This library owns the source-grounded subject schema, shared semantic model
instruction, and deterministic subject-to-route validation. It does not infer
categories from keywords, tickers, publishers, templates, or section names.
`news_subject.py` performs no I/O. The separate `news_identity.py` allows only
bounded read-only Yahoo company/security discovery, never arbitrary URLs,
source-state mutation, model calls, delivery, or extra news facts. Require
unique normalized company-name and exchange agreement; ambiguity or failure
retains company-name Stock News without a tracker.

Keep category and security resolution separate. Company, industry and macro
are semantic subjects. An unknown ticker never changes a company into Macro.
Source owners enforce the new contract at claim and submission boundaries;
already frozen output and outstanding legacy leases remain compatible.

Run `python -m pytest -q tests`. Include cases with company examples in sector
stories, sector context in company stories, tickerless named companies,
industry-focused government policy, and broad policy with company examples.

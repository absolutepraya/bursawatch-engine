# News subject classification

`bin/news_subject.py` is the shared contract for ordinary Company, Industry,
and Macro news. Existing source-analysis agents identify the central subject
and quote its supporting evidence in the same analysis call. Owners validate
the subject against their supplied source and derive the destination category.
No source name, headline template, company list, sector keyword list, or
ticker position decides a category.

Company identity and subject classification are separate: a source-grounded
company name can produce Stock News without a verified ticker or quote.
Sector-wide stories remain Industry News when companies are examples. Broad
economic stories remain Macro News when companies or sectors are examples.
Independent company stories split; a connected transaction stays together.

`news_subject.py` has no I/O. The separate `news_identity.py` performs bounded
read-only Yahoo Finance searches for exact company-name and exchange matches.
It has no credentials, source state, model calls, or message delivery.
Owners expose `lookup-company` through their managed wrappers. An externally
proposed ticker is independently verified before selection is persisted;
unresolved identity falls back to company-name Stock News without a tracker. Owners retain source eligibility, market coverage, intake, leases,
frozen destinations, and delivery receipts. Specialized Swing and Stock
Information retain their separate contracts. Old frozen output is never
reclassified. A lease records the new contract before requiring its subject
object, so an already outstanding legacy lease can settle normally.

Run `python -m pytest -q lib-news-classification/tests`. Deploy this library
before its consumer owners through the reviewed release manifest or the
separately approved library deployment helper.

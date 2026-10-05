# Category news contracts

Terms for the [shared-category discussion](../notes/2026-10-03-shared-category-contracts-working-notes.md).
Common source, publisher, and prepared-card terms remain in the
[stock-news glossary](stock-news.md).

## Language

**Category contract**:
The presentation obligations that preserve the meaning of news in a category,
including distinctions between source facts and interpretation.
_Avoid_: Delivery gate, routing policy

**Presentation category**:
The kind of content being presented, such as Macro, Industry, or Swing,
independent of the name of its delivery route.
_Avoid_: Channel, platform source, route enum

**Additional image context**:
Information read from an associated source image to clarify a news summary
after the publication's text independently establishes eligibility.
_Avoid_: Primary news content, image-based eligibility screening

**Actual figure**:
A value the source reports as observed for a specified period, retaining any
provisional or revised qualification.
_Avoid_: Forecast, guaranteed final value

**Forecast figure**:
A prediction or estimate attributed to its source for a stated period or
horizon; a consensus forecast is attributed to the reported consensus.
_Avoid_: Actual figure, unattributed expectation

**Reference period**:
The period a reported figure describes, distinct from the publication date or
the date of an upcoming event.
_Avoid_: Publication date, assumed current period

**Measurement basis**:
The unit and comparison basis that give a figure meaning, including YoY,
MoM, percent, and percentage points.
_Avoid_: Interchangeable percentage labels

**Reported industry fact**:
A development or measurement supported by the publication, with its original
attribution and uncertainty retained.
_Avoid_: Assumed company benefit, price prediction

**Evidence-backed company impact**:
An explicitly qualified implication supported by a company's specific
business exposure and a stated mechanism connecting it to the development.
_Avoid_: Sector resemblance, guaranteed beneficiary, reported contract award

**Source level**:
A publisher's stated setup value, range, or comparison operator, retaining
its ordering and existing canonical representation separately from market
calculations.
_Avoid_: LLM-generated level, calculated midpoint, substituted market price

**Base plan display fields**:
Entry, Stop-loss, and Target 1 slots shown on a source-plan card, with
`-` when a value is not supplied. Their presence does not establish a complete
or eligible Board plan.
_Avoid_: Required source values, Board promotion criteria

**Plan synonym normalization**:
Recognition of approved source terms as canonical plan fields while retaining
source levels and conditions. Watch on/Buy area means Entry; Support utama
means Stop-loss, with an unqualified level interpreted as a stop below it.
_Avoid_: Invented price level, inferred Board state, arbitrary support mapping

**Source status**:
The publisher's stated status of a Swing setup at its source date, retained
separately from any later Board lifecycle state.
_Avoid_: Board state, inferred recommendation

**Board lifecycle state**:
The Board owner's state of an episode under its deterministic lifecycle
rules, separate from the publisher's source status.
_Avoid_: LLM assessment, rewritten source status

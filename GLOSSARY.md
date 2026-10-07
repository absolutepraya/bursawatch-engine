# Morning Brief and Closing Review

Vocabulary for the proposed market-research workflow in this design worktree. These definitions do not describe an implemented or deployed product.

The [morning brief spec](docs/notes/2026-09-27-bursawatch-morning-brief-design-spec.md) is the active design focus; the [after-close review spec](docs/notes/2026-10-04-bursawatch-after-close-review-design-spec.md) preserves the deferred extension.

## Language

**Morning brief**:
A dated pre-market publication presenting an IHSG outlook, its evidence, and relevant sector and conglomerate rotation context.

**Morning outlook**:
A conditional assessment covering the coming IHSG trading session as a whole, based on information available at the morning evidence cutoff.
_Avoid_: Guaranteed prediction, calibrated probability without measured evidence.

**IHSG evidence bundle**:
A bounded collection of relevant, source-attributed information available by a brief's evidence cutoff. Its contents are selected evidence rather than a claim of complete market commentary coverage.

**Narrative pulse**:
A concise account of the optimistic and cautious views expressed by qualifying sources, including their disagreements. It describes collected commentary rather than a representative poll or measured probability of an IHSG move.

**Original publisher**:
The person or organization responsible for a source item, independently of the channels through which copies are distributed. Forwarding the same publication through another channel does not create an independent source view.

**Facts-only brief**:
A morning publication of verified observations and available charts when the generated outlook is unavailable. It makes the absence of analysis explicit.

**Evidence cutoff**:
The latest time at which information may enter a particular assessment. Information received afterward belongs to a later assessment rather than a rewrite of the original view.

**Closing review**:
A same-session publication comparing the frozen morning outlook with observed IHSG behavior and summarizing material market activity and news.
_Avoid_: Revised morning outlook.

**Sector basket**:
A portfolio of stocks grouped by the chosen sector classification. Its calculated return is distinct from the return of an official exchange sector index.

**Weight snapshot**:
A dated set of member market-cap weights used to calculate a basket's return.

**Basket price coverage**:
The share of a basket's total snapshot market cap represented by members with usable price history for the same calculation period. It cannot be measured reliably when mapped members lack valid snapshot weights.

**Fixed-snapshot rotation**:
A relative-rotation illustration calculated from historical member returns using one dated percentage allocation throughout the calculation history. Earlier positions incorporate that snapshot's information and are not historically knowable cap-weighted observations.

**Conglomerate basket**:
A portfolio of stocks associated with one conglomerate under the dated membership reference. A stock may belong to more than one such basket.

**Daily basket return**:
The change in a basket over one trading session, calculated from member returns and the agreed dated weights.

**Price return**:
The change in an investment's price on compatible split-adjusted units, excluding cash dividend reinvestment. This is the agreed basis for comparing basket performance with the IHSG price index.
_Avoid_: Total return, dividend-adjusted return.

**Market-cap snapshot**:
A retained collection of member market-cap values used as a weighting reference. Its collection time is distinct from the underlying economic date of those values, which may be unknown.

**Top daily performers**:
The sectors or conglomerate baskets with the highest daily basket returns within their category. The ranking includes negative returns when they are among the strongest available performances.
_Avoid_: Gainers when ranked returns are negative.

**Relative rotation**:
The position and movement of a basket's relative strength and relative momentum against IHSG. Relative leadership alone does not establish a positive absolute return.

**Relative strength gap**:
The basket's compounded ten-session return minus IHSG's compounded ten-session return, expressed in percentage points. A positive gap means the basket outperformed IHSG over that period.

**Relative momentum**:
The change in a basket's relative strength gap over three trading sessions, expressed in percentage points. A positive value means the gap improved over that interval.

**Rotation trail**:
A sequence of a basket's dated relative-rotation positions leading to its latest position. The number of displayed observations is distinct from the lookback windows used to calculate each position.

**Trading volume**:
The number of shares traded during a specified interval and market scope.
_Avoid_: Trading value.

**Trading value**:
The rupiah value of executed trades during a specified interval and market scope.
_Avoid_: Trading volume, closing price multiplied by volume.

**Net foreign flow**:
Foreign buying value minus foreign selling value for a specified interval and market scope. A positive value indicates net buying and a negative value indicates net selling.

# Morning Brief and Closing Review

Vocabulary for the proposed market-research workflow in this design worktree. These definitions do not describe an implemented or deployed product.

The [morning brief spec](docs/notes/2026-09-27-bursawatch-morning-brief-design-spec.md) is the active design focus; the [after-close review spec](docs/notes/2026-10-04-bursawatch-after-close-review-design-spec.md) preserves the deferred extension.

## Language

**Morning brief**:
A dated pre-market publication presenting an IHSG outlook, its evidence, and relevant sector and conglomerate rotation context.

**Morning outlook**:
A conditional assessment of the coming IHSG session based on information available at the morning evidence cutoff.
_Avoid_: Guaranteed prediction, calibrated probability without measured evidence.

**Evidence cutoff**:
The latest time at which information may enter a particular assessment. Information received afterward belongs to a later assessment rather than a rewrite of the original view.

**Closing review**:
A same-session publication comparing the frozen morning outlook with observed IHSG behavior and summarizing material market activity and news.
_Avoid_: Revised morning outlook.

**Sector basket**:
A portfolio of stocks grouped by the chosen sector classification. Its calculated return is distinct from the return of an official exchange sector index.

**Conglomerate basket**:
A portfolio of stocks associated with one conglomerate under the dated membership reference. A stock may belong to more than one such basket.

**Daily basket return**:
The change in a basket over one trading session, calculated from member returns and the agreed dated weights.

**Top daily performers**:
The sectors or conglomerate baskets with the highest daily basket returns within their category. The ranking includes negative returns when they are among the strongest available performances.
_Avoid_: Gainers when ranked returns are negative.

**Relative rotation**:
The position and movement of a basket's relative strength and relative momentum against IHSG. Relative leadership alone does not establish a positive absolute return.

**Trading volume**:
The number of shares traded during a specified interval and market scope.
_Avoid_: Trading value.

**Trading value**:
The rupiah value of executed trades during a specified interval and market scope.
_Avoid_: Trading volume, closing price multiplied by volume.

**Net foreign flow**:
Foreign buying value minus foreign selling value for a specified interval and market scope. A positive value indicates net buying and a negative value indicates net selling.

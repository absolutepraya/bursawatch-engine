"""Fixed-cap basket rotation illustrations, not unbiased historical backtests."""
from dataclasses import dataclass
from datetime import date
import math
from .inputs import CapSnapshot, PriceSeries, ActionDecision, compatible_closes, positive, symbol, NumericalInputs


class UnsupportedBasket(ValueError): pass


@dataclass(frozen=True)
class Position:
    session: str
    x: float
    y: float
    quadrant: str


@dataclass(frozen=True)
class BasketResult:
    name: str
    trail: tuple[Position,...]
    previous_quadrant: str
    changed_quadrant: bool
    coverage: float
    weights: dict[str,float]
    excluded: dict[str,str]
    aligned_closes: dict[str,tuple[float,...]]
    action_decisions: tuple[ActionDecision,...]
    provenance: dict

    @property
    def x(self): return self.trail[-1].x
    @property
    def y(self): return self.trail[-1].y
    @property
    def quadrant(self): return self.trail[-1].quadrant


@dataclass(frozen=True)
class GroupRanking:
    name: str
    x: float
    y: float
    quadrant: str
    changed_quadrant: bool


def quadrant(x: float, y: float) -> str:
    if not math.isfinite(x) or not math.isfinite(y): raise ValueError('finite coordinates required')
    if x == 0 or y == 0: return 'Neutral'
    if x > 0: return 'Leading' if y > 0 else 'Weakening'
    return 'Improving' if y > 0 else 'Lagging'


def calculate_basket(name: str, members: tuple[str,...], caps: CapSnapshot,
                     prices: dict[str,PriceSeries], benchmark: dict[str,float], sessions: tuple[date,...],
                     *, provenance: dict, actions: tuple[ActionDecision,...] = ()) -> BasketResult:
    if len(sessions) != 18 or tuple(sorted(set(sessions))) != sessions:
        raise ValueError('exactly 18 aligned verified closing levels required')
    members = tuple(sorted(symbol(m) for m in members))
    if not name or not members or len(set(members)) != len(members): raise ValueError('unique basket members required')
    original, excluded = {}, {}
    for member in members:
        try: original[member] = positive(caps.values[member])
        except (KeyError, ValueError): excluded[member] = 'missing_or_invalid_cap'
    dates = tuple(s.isoformat() for s in sessions)
    try: index = tuple(positive(benchmark[d]) for d in dates)
    except (KeyError,ValueError): raise UnsupportedBasket('missing benchmark session') from None
    aligned = {}
    for member in members:
        if member not in original: continue
        if member not in prices:
            excluded[member] = 'missing_price_series'; continue
        if prices[member].symbol != member:
            excluded[member] = 'symbol_mismatch'; continue
        try: adjusted = compatible_closes(prices[member], list(actions))
        except ValueError:
            excluded[member] = 'unresolved_action_or_eligibility'; continue
        if any(d not in adjusted for d in dates):
            excluded[member] = 'missing_session'; continue
        aligned[member] = tuple(adjusted[d] for d in dates)
    covered = math.fsum(original[m] for m in sorted(aligned))
    total = math.fsum(original.values())
    if not aligned or covered <= 0: raise UnsupportedBasket('no usable cap and aligned price members')
    weights = {m:original[m]/covered for m in sorted(aligned)}
    daily = [math.fsum(weights[m]*(aligned[m][t]/aligned[m][t-1]-1.) for m in weights) for t in range(1,18)]
    x = {}
    for t in range(10,18):
        basket_return = math.prod(1.+d for d in daily[t-10:t])-1.
        index_return = index[t]/index[t-10]-1.
        x[t] = 100.*(basket_return-index_return)
    positions = {}
    for t in range(13,18):
        px,py = x[t],x[t]-x[t-3]
        positions[t] = Position(dates[t],px,py,quadrant(px,py))
    refs = dict(provenance)
    refs.update(cap_snapshot=caps.identity,cap_digest=caps.provenance.digest,
                cap_collected_at=caps.collected_at.isoformat(), cap_effective_date=caps.effective_date.isoformat() if caps.effective_date else None,
                price_versions={m:prices[m].version for m in sorted(aligned)},
                action_identities=tuple(sorted(a.identity for a in actions if a.symbol in members)),
                missing_cap_members=tuple(m for m in members if m not in original),
                coverage_basis='known-original-caps',
                illustration='fixed-current-cap/not-unbiased-backtest')
    trail = tuple(positions.values())
    return BasketResult(name,trail,trail[-2].quadrant,trail[-1].quadrant!=trail[-2].quadrant,
                        covered/total,weights,excluded,aligned,tuple(actions),refs)


def select_groups(groups, *, limit: int = 18):
    if type(limit) is not int or not 0 <= limit <= 18: raise ValueError('selection limit from zero to 18 required')
    _validate_rankings(groups)
    return tuple(sorted(groups,key=lambda r:(not r.changed_quadrant,-abs(r.y),r.name))[:limit])


def table_order(groups):
    _validate_rankings(groups)
    order = {'Leading':0,'Improving':1,'Weakening':2,'Lagging':3,'Neutral':4}
    return tuple(sorted(groups,key=lambda r:(order[r.quadrant],-r.x,-r.y,r.name)))


def unselected_letters(groups, selected):
    _validate_rankings(groups)
    chosen = {r.name for r in selected}
    if not chosen <= {r.name for r in groups}: raise ValueError('selection outside qualifying groups')
    names = sorted(r.name for r in groups if r.name not in chosen)
    if len(names)>26: raise ValueError('single-letter mapping exhausted')
    return {name:chr(ord('A')+n) for n,name in enumerate(names)}


def _validate_rankings(groups):
    names = [r.name for r in groups]
    if len(set(names)) != len(names) or any(not n for n in names): raise ValueError('unique group names required')
    for row in groups:
        if row.quadrant != quadrant(row.x,row.y): raise ValueError('coordinate quadrant mismatch')


def calculate_from_inputs(name: str, inputs: NumericalInputs) -> BasketResult:
    """Production-facing pure calculation preserving validated snapshot provenance."""
    if name not in inputs.membership.groups:
        raise UnsupportedBasket('group absent from versioned membership')
    return calculate_basket(name,inputs.membership.groups[name],inputs.caps,inputs.prices,
                            inputs.benchmark,inputs.sessions,provenance=inputs.provenance,actions=inputs.actions)

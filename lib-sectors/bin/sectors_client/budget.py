"""Conservative credit reservation. Caller supplies a shared billing-window identity."""
from .models import BudgetDenied, ValidationError


def reserve_credits(db, config, request_key, token, max_cost):
    if type(max_cost) is not int or max_cost <= 0:
        raise ValidationError('request requires a positive conservative credit cost')
    # Only explicitly configured limits apply. No implicit provider quota.
    # A capped client can tighten a durable limit, but cannot enlarge it.
    for caller, maximum in (('*host*', config.host_limit), (config.caller, config.caller_limit)):
        if maximum is None:
            continue
        db.execute('INSERT INTO limits VALUES (?,?,?) ON CONFLICT(window,caller) DO UPDATE SET maximum=MIN(maximum,excluded.maximum)', (config.billing_window, caller, maximum))
        ceiling = db.execute('SELECT maximum FROM limits WHERE window=? AND caller=?', (config.billing_window, caller)).fetchone()[0]
        if caller == '*host*':
            used = db.execute('SELECT COALESCE(SUM(cost),0) FROM reservations WHERE window=?', (config.billing_window,)).fetchone()[0]
        else:
            used = db.execute('SELECT COALESCE(SUM(cost),0) FROM reservations WHERE window=? AND caller=?', (config.billing_window, caller)).fetchone()[0]
        if used + max_cost > ceiling:
            raise BudgetDenied('conservative provider credit reservation denied')
    db.execute("INSERT INTO reservations VALUES (?,?,?,?,?,'reserved')", (token, request_key, config.billing_window, config.caller, max_cost))

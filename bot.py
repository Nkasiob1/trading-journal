# bot.py
# GOAT Trading Bot - Rule Engine
# v7.0 -- Mean-reversion module added, account-wide max-loss tightened to 9%
#
# v7.0 CHANGE: MAX_LOSS_PCT tightened from 0.10 (FTMO's real limit) to 0.09 -- a self-
# imposed 1% safety buffer below the real breach point, validated across a full
# mean-reversion backtest (8 independent quarters, 6 of 8 reached $1,000+ peak profit
# before any breach at this threshold). This applies account-wide, to both the ICT
# engine and the new mean-reversion engine, since it's a single real FTMO account with
# one real drawdown floor.
#
# Added evaluate_mean_reversion_signal() -- a deliberately SIMPLER evaluation path for
# the new mean-reversion strategies (Bollinger+RSI14, RSI2, VWAP -- see mean_reversion.py).
# Does NOT use the ICT checklist (weekly_bias, zone, SMT, window, FVG) at all -- those
# concepts don't apply to mean reversion. Still enforces: real account drawdown status,
# real news blackout calendar, and market-open/weekend checks.
#
# v6.2 CHANGE (kept): weights reverted to original v5.0 best-backtested values
# (weekly_bias=25, bias_4h=20, smt=15, price_action_5m=20, threshold=85), FVG/OB no
# longer a hard requirement for the ICT engine specifically -- backtested across 16
# months, dropping it took the best ICT result from 65 trades/+$3,381.64 to
# 234 trades/+$8,567.35.
#
# v5.0 CHANGE (kept): `window_required` in PAIR_PROFILES -- DE40/XAUUSD/EURUSD scan
# continuously for the ICT engine specifically. GBPUSD/USTEC/US30/US500 keep
# window-gated behavior. (Mean reversion, added in v7.0, ignores this entirely -- it
# scans all 7 pairs continuously, unrelated to Silver Bullet windows.)

from datetime import datetime, time as dtime
import pytz
import math
from news import get_forex_news, get_trade_verdict

WAT = pytz.timezone('Africa/Lagos')
CET = pytz.timezone('Europe/Prague')

# ── ACCOUNT ──
INITIAL_CAPITAL = 10000
DAILY_LOSS_PCT = 0.03
MAX_LOSS_PCT = 0.09   # tightened from FTMO's real 0.10 -- see v7.0 note above

# ── ICT ENGINE PARAMETERS ──
PAIR_RISK = {
    'XAUUSD': 200, 'EURUSD': 200, 'GBPUSD': 200,
    'USTEC': 200, 'US30': 100, 'US500': 100, 'DE40': 100,
}

POINT_VALUES = {
    'EURUSD': 1.00, 'GBPUSD': 1.00, 'XAUUSD': 1.00,
    'USTEC': 1.00, 'US30': 1.00, 'US500': 1.00,
    'DE40': 1.15,   # EUR-denominated, drifts with EUR/USD -- re-verify periodically
}
POINT_SCALE = {'EURUSD': 100000, 'GBPUSD': 100000, 'XAUUSD': 100,
                'USTEC': 1, 'US30': 1, 'US500': 1, 'DE40': 1}
MIN_LOT = 0.01
MAX_LOT = 1.00

def get_account_for_pair(pair):
    return 'FTMO Account'

PAIR_PROFILES = {
    'EURUSD': {'trend_required': True,  'zone_required': True,  'window_required': False},
    'GBPUSD': {'trend_required': True,  'zone_required': True,  'window_required': True},
    'XAUUSD': {'trend_required': True,  'zone_required': True,  'window_required': False},
    'USTEC':  {'trend_required': False, 'zone_required': True,  'window_required': True},
    'US30':   {'trend_required': False, 'zone_required': False, 'window_required': True},
    'US500':  {'trend_required': True,  'zone_required': True,  'window_required': True},
    'DE40':   {'trend_required': True,  'zone_required': False, 'window_required': False},
}
DEFAULT_PROFILE = {'trend_required': True, 'zone_required': True, 'window_required': True}

def get_pair_profile(pair):
    return PAIR_PROFILES.get(pair, DEFAULT_PROFILE)

# ── KILL SWITCH (shared logic, used with SEPARATE counters per strategy -- ICT, mean
# reversion, and manual trades each get their own consecutive_losses tracking, so a bad
# streak in one doesn't wrongly pause a different one) ──
MAX_CONSECUTIVE_LOSSES = 3
KILL_SWITCH_HOURS = 24

def check_kill_switch(consecutive_losses, last_loss_timestamp=None, now_override=None):
    now_fn = (lambda: now_override) if now_override else (lambda: datetime.now(WAT))
    if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        if last_loss_timestamp:
            now = now_fn()
            hours_since_loss = (now - last_loss_timestamp).total_seconds() / 3600
            if hours_since_loss < KILL_SWITCH_HOURS:
                remaining = round(KILL_SWITCH_HOURS - hours_since_loss, 1)
                return {'triggered': True, 'reason': f"Kill switch active -- {remaining}h remaining.",
                        'hours_remaining': remaining, 'consecutive_losses': consecutive_losses}
            return {'triggered': False, 'reason': "Kill switch cooldown complete.",
                    'consecutive_losses': consecutive_losses}
        return {'triggered': True, 'reason': "Kill switch active, no timestamp -- pause manually.",
                'consecutive_losses': consecutive_losses}
    return {'triggered': False, 'reason': f"{consecutive_losses} consecutive losses (threshold {MAX_CONSECUTIVE_LOSSES}).",
            'consecutive_losses': consecutive_losses}

# ── FTMO-SPECIFIC DRAWDOWN LOGIC (account-wide, shared by every strategy) ──
def get_cet_day_boundary(dt_wat):
    return dt_wat.astimezone(CET).date()

def compute_daily_floors(daily_closing_balances, initial_capital):
    if not daily_closing_balances:
        yesterday_close = initial_capital
        peak_close = initial_capital
    else:
        dates_sorted = sorted(daily_closing_balances.keys())
        yesterday_close = daily_closing_balances[dates_sorted[-1]]
        peak_close = max(list(daily_closing_balances.values()) + [initial_capital])
    daily_floor = yesterday_close - (DAILY_LOSS_PCT * initial_capital)
    max_loss_floor = peak_close - (MAX_LOSS_PCT * initial_capital)
    return daily_floor, max_loss_floor

def check_account_status(current_equity, daily_floor, max_loss_floor):
    if current_equity <= max_loss_floor:
        return {'can_trade': False, 'reason': f"Max Loss breached: equity {current_equity:.2f} <= floor {max_loss_floor:.2f}"}
    if current_equity <= daily_floor:
        return {'can_trade': False, 'reason': f"Daily Loss breached: equity {current_equity:.2f} <= floor {daily_floor:.2f}"}
    return {'can_trade': True, 'reason': 'Account within FTMO limits'}

def check_best_day_rule(daily_pnl_by_date):
    positive_days = {d: p for d, p in daily_pnl_by_date.items() if p > 0}
    if not positive_days:
        return {'compliant': True, 'best_day_pct': 0, 'reason': 'No positive days yet'}
    total_positive = sum(positive_days.values())
    best_day = max(positive_days.values())
    pct = (best_day / total_positive) * 100 if total_positive > 0 else 0
    compliant = pct <= 50
    return {'compliant': compliant, 'best_day_pct': round(pct, 1),
            'reason': f"Best day is {pct:.1f}% of positive-day profit "
                      f"({'OK' if compliant else 'need more profitable days before this counts toward passing'})"}

# ── NEWS CHECK (shared, hard requirement for every strategy) ──
def check_news_status():
    from news import check_economic_calendar_blackout
    now_utc = datetime.now(WAT).astimezone(pytz.UTC)
    calendar_check = check_economic_calendar_blackout(now_utc)
    if calendar_check['in_blackout']:
        if calendar_check['severity'] == 'NO TRADE':
            return {'can_trade': False, 'category': 1, 'reason': calendar_check['reason'], 'caution': False}
        else:
            return {'can_trade': True, 'category': 2, 'reason': calendar_check['reason'], 'caution': True}
    return {'can_trade': True, 'category': 3, 'reason': 'No scheduled high/medium impact events nearby', 'caution': False}

# ── SESSIONS (ICT engine only -- mean reversion ignores this entirely) ──
SILVER_BULLET_WINDOWS = {
    'Asian KZ':       {'pair': 'EURUSD/GBPUSD/XAUUSD', 'start': dtime(0, 0),  'end': dtime(1, 0)},
    'London Open KZ': {'pair': 'EURUSD/GBPUSD/XAUUSD/DE40', 'start': dtime(8, 0),  'end': dtime(9, 0)},
    'London':         {'pair': 'EURUSD/GBPUSD', 'start': dtime(9, 0),  'end': dtime(10, 0)},
    'Gold NY':        {'pair': 'XAUUSD', 'start': dtime(13, 30), 'end': dtime(14, 30)},
    'Forex NY':       {'pair': 'EURUSD/GBPUSD', 'start': dtime(15, 0),  'end': dtime(16, 0)},
    'NASDAQ PM':      {'pair': 'USTEC/US30/US500', 'start': dtime(15, 0), 'end': dtime(16, 0)},
}

def check_silver_bullet_window(now_override=None):
    now = now_override if now_override else datetime.now(WAT)
    current_time = now.time()
    for session_name, window in SILVER_BULLET_WINDOWS.items():
        if window['start'] <= current_time < window['end']:
            return {'active': True, 'session': session_name}
    return {'active': False, 'session': None}

def is_weekend(now_override=None):
    now = now_override if now_override else datetime.now(WAT)
    return now.weekday() in [5, 6]

def is_friday_close(now_override=None):
    now = now_override if now_override else datetime.now(WAT)
    return now.weekday() == 4 and now.hour >= 22

# ── POSITION SIZING (ICT engine) ──
def calculate_lot_size(pair, sl_points):
    if sl_points <= 0:
        return {'valid': False, 'reason': 'SL distance must be greater than zero'}
    if pair not in POINT_VALUES or pair not in PAIR_RISK:
        return {'valid': False, 'reason': f'Unknown pair: {pair}'}
    risk_amount = PAIR_RISK[pair]
    point_value = POINT_VALUES[pair]
    raw_lot = risk_amount / (sl_points * point_value)
    lot_size = math.floor(raw_lot * 100) / 100
    if lot_size < MIN_LOT:
        return {'valid': False, 'reason': f'Lot size {lot_size} below minimum {MIN_LOT}.', 'sl_points': sl_points}
    if lot_size > MAX_LOT:
        lot_size = MAX_LOT
    actual_risk = lot_size * sl_points * point_value
    return {'valid': True, 'pair': pair, 'lot_size': lot_size, 'sl_points': sl_points,
            'risk_amount': round(actual_risk, 2), 'expected_reward': round(actual_risk * 2, 2)}

def verify_rr_ratio(sl_points, tp_points):
    if sl_points <= 0 or tp_points <= 0:
        return {'valid': False, 'reason': 'SL and TP distances must both be greater than zero'}
    actual_ratio = tp_points / sl_points
    if actual_ratio < 2.0:
        return {'valid': False, 'actual_ratio': round(actual_ratio, 2), 'reason': f'R:R is 1:{round(actual_ratio,2)} -- minimum is 1:2'}
    return {'valid': True, 'actual_ratio': round(actual_ratio, 2), 'reason': f'R:R verified: 1:{round(actual_ratio,2)}'}

# ── CONFIDENCE SCORING (ICT engine) ──
RULE_WEIGHTS = {
    'account_status': 0, 'news_check': 10, 'market_open': 0, 'silver_bullet_window': 0, 'zone': 0,
    'weekly_bias': 25, 'bias_4h': 20, 'smt': 15, 'price_action_5m': 20, 'rr_ratio': 10,
}
MIN_CONFIDENCE = 85
CATEGORY_2_PENALTY = 5

def calculate_confidence(results, news_caution=False):
    total_score = 0
    max_possible = sum(w for rule, w in RULE_WEIGHTS.items() if w > 0)
    scored_rules = {}
    for rule, weight in RULE_WEIGHTS.items():
        if weight == 0 or rule not in results:
            continue
        result = results[rule]
        if result.get('passed'):
            total_score += weight
            scored_rules[rule] = {'weight': weight, 'earned': weight, 'passed': True}
        else:
            scored_rules[rule] = {'weight': weight, 'earned': 0, 'passed': False}
    if news_caution:
        total_score = max(0, total_score - CATEGORY_2_PENALTY)
    confidence = round((total_score / max_possible) * 100, 1)
    if confidence >= 95: grade, recommendation = 'A+', 'EXCEPTIONAL SETUP -- HIGH CONVICTION TRADE'
    elif confidence >= 90: grade, recommendation = 'A', 'STRONG SETUP -- TAKE THE TRADE'
    elif confidence >= 85: grade, recommendation = 'B', 'GOOD SETUP -- TAKE THE TRADE'
    elif confidence >= 75: grade, recommendation = 'C', 'MARGINAL SETUP -- STAND ASIDE'
    else: grade, recommendation = 'D', 'WEAK SETUP -- DO NOT TRADE'
    return {'score': confidence, 'grade': grade, 'recommendation': recommendation,
            'meets_threshold': confidence >= MIN_CONFIDENCE, 'scored_rules': scored_rules,
            'news_caution_applied': news_caution}

# ── MAIN ICT FUNCTION ──
def evaluate_checklist(current_equity, daily_floor, max_loss_floor, pair, direction,
                        weekly_bias, bias_4h, sma_50_slope, zone, smt_agreement,
                        smt_divergence, fvg_or_ob, liquidity_swept, bos_confirmed,
                        sl_points, tp_points, now_override=None):
    profile = get_pair_profile(pair)
    results = {}

    acc_status = check_account_status(current_equity, daily_floor, max_loss_floor)
    results['account_status'] = {'passed': acc_status['can_trade'], 'reason': acc_status['reason']}

    news_status = check_news_status()
    results['news_check'] = {'passed': news_status['can_trade'], 'reason': news_status['reason'],
                              'caution': news_status.get('caution', False)}

    weekend = is_weekend(now_override)
    friday_close = is_friday_close(now_override)
    results['market_open'] = {'passed': not weekend and not friday_close,
                               'reason': 'Weekend' if weekend else 'Friday after 22:00 WAT' if friday_close else 'Market open'}

    if profile['window_required']:
        window = check_silver_bullet_window(now_override)
        results['silver_bullet_window'] = {'passed': window['active'],
                                            'reason': f"Active session: {window['session']}" if window['active'] else 'Outside window'}
    else:
        results['silver_bullet_window'] = {'passed': True, 'reason': f'{pair} scans continuously, no window restriction'}

    if profile['trend_required']:
        weekly_bias_valid = weekly_bias in ['bullish', 'bearish']
        weekly_direction_match = ((weekly_bias == 'bullish' and direction == 'buy') or (weekly_bias == 'bearish' and direction == 'sell'))
        results['weekly_bias'] = {'passed': weekly_bias_valid and weekly_direction_match, 'reason': f'Weekly bias {weekly_bias}'}
        bias_4h_matches_weekly = bias_4h == weekly_bias
        sma_matches_direction = ((direction == 'buy' and sma_50_slope == 'up') or (direction == 'sell' and sma_50_slope == 'down'))
        results['bias_4h'] = {'passed': bias_4h_matches_weekly and sma_matches_direction, 'reason': f'4H bias {bias_4h}'}
    else:
        results['weekly_bias'] = {'passed': True, 'reason': f'Weekly bias {weekly_bias} (not required for {pair})'}
        results['bias_4h'] = {'passed': True, 'reason': f'4H bias {bias_4h} (not required for {pair})'}

    zone_valid = ((direction == 'buy' and zone == 'discount') or (direction == 'sell' and zone == 'premium'))
    results['zone'] = {'passed': zone_valid, 'reason': f'Zone {zone} for {direction}', 'enforced': profile['zone_required']}

    smt_valid = smt_agreement or smt_divergence
    results['smt'] = {'passed': smt_valid, 'reason': 'SMT valid' if smt_valid else 'SMT invalid'}

    price_action_valid = liquidity_swept and bos_confirmed
    results['price_action_5m'] = {'passed': price_action_valid, 'reason': f'sweep={liquidity_swept} bos={bos_confirmed} (fvg={fvg_or_ob}, no longer required)'}

    rr = verify_rr_ratio(sl_points, tp_points)
    results['rr_ratio'] = {'passed': rr['valid'], 'reason': rr['reason']}

    lot_calc = calculate_lot_size(pair, sl_points)
    results['lot_size'] = {'valid': lot_calc['valid'], 'details': lot_calc}

    news_caution = results['news_check']['caution']
    confidence = calculate_confidence(results, news_caution)

    hard_stops_list = [
        results['account_status']['passed'],
        results['market_open']['passed'],
        results['silver_bullet_window']['passed'],
        results['news_check']['passed'],
    ]
    if profile['zone_required']:
        hard_stops_list.append(results['zone']['passed'])
    hard_stops_passed = all(hard_stops_list)

    lot_valid = lot_calc['valid']
    all_passed = hard_stops_passed and confidence['meets_threshold'] and lot_valid

    passed_count = sum(1 for v in results.values() if 'passed' in v and v['passed'])
    total_count = sum(1 for v in results.values() if 'passed' in v)
    signal = 'VALID SETUP -- LOOK FOR ENTRY' if all_passed else 'INVALID SETUP -- STAND ASIDE'

    return {
        'signal': signal, 'valid': all_passed, 'passed': passed_count, 'total': total_count,
        'confidence': confidence['score'], 'grade': confidence['grade'], 'recommendation': confidence['recommendation'],
        'pair': pair, 'direction': direction,
        'lot_size': lot_calc.get('lot_size') if lot_valid else None,
        'sl_points': sl_points, 'tp_points': tp_points,
        'risk_amount': lot_calc.get('risk_amount') if lot_valid else None,
        'expected_reward': lot_calc.get('expected_reward') if lot_valid else None,
        'checklist': results, 'confidence_breakdown': confidence['scored_rules'],
        'pair_profile_used': profile,
    }


# ── MEAN REVERSION EVALUATION (v7.0, new) ──
# Deliberately simpler than the ICT checklist -- no weekly_bias, zone, SMT, window, or
# FVG concepts apply here. Just the real, hard account-level and compliance checks that
# genuinely matter for ANY strategy trading this account, plus basic sizing sanity.
def evaluate_mean_reversion_signal(current_equity, daily_floor, max_loss_floor, pair,
                                     direction, sl_dist, point_scale, point_value,
                                     now_override=None):
    import mean_reversion as mr
    results = {}

    acc_status = check_account_status(current_equity, daily_floor, max_loss_floor)
    results['account_status'] = {'passed': acc_status['can_trade'], 'reason': acc_status['reason']}

    news_status = check_news_status()
    results['news_check'] = {'passed': news_status['can_trade'], 'reason': news_status['reason'],
                              'caution': news_status.get('caution', False)}

    weekend = is_weekend(now_override)
    friday_close = is_friday_close(now_override)
    results['market_open'] = {'passed': not weekend and not friday_close,
                               'reason': 'Weekend' if weekend else 'Friday after 22:00 WAT' if friday_close else 'Market open'}

    lot_calc = mr.calculate_mr_lot_size(pair, sl_dist, point_scale, point_value)
    results['lot_size'] = {'valid': lot_calc['valid'], 'details': lot_calc}

    hard_stops = [results['account_status']['passed'], results['market_open']['passed'],
                  results['news_check']['passed'], lot_calc['valid']]
    all_passed = all(hard_stops)

    return {
        'valid': all_passed, 'pair': pair, 'direction': direction,
        'lot_size': lot_calc.get('lot_size') if lot_calc['valid'] else None,
        'risk_amount': lot_calc.get('risk_amount') if lot_calc['valid'] else None,
        'checklist': results,
    }
# bot.py
# GOAT Trading Bot - Rule Engine
# Built strictly according to documented Silver Bullet strategy
# Version 2.0 — Confidence Scoring Added

from datetime import datetime, time as dtime
import pytz
import math
from news import get_forex_news, get_trade_verdict

WAT = pytz.timezone('Africa/Lagos')

# ── ACCOUNT CONFIGURATION ──
ACCOUNTS = {
    'Account 1': {
        'pair': 'XAUUSD',
        'balance': 1000,
        'risk_per_trade': 10,
        'daily_loss_limit': 30,
        'total_drawdown_limit': 50,
    },
    'Account 2': {
        'pair': 'EURUSD/GBPUSD',
        'balance': 1000,
        'risk_per_trade': 10,
        'daily_loss_limit': 30,
        'total_drawdown_limit': 50,
    }
}

# ── CONFIDENCE SCORING WEIGHTS ──
# Each rule is assigned a weight reflecting its importance
# Total possible score = 100
# Trade only if confidence >= 85

RULE_WEIGHTS = {
    'account_status':       0,   # Hard stop
    'news_check':           10,
    'market_open':          0,   # Hard stop
    'silver_bullet_window': 0,   # Hard stop
    'zone':                 0,   # Hard stop — NEVER buy premium, NEVER sell discount
    'weekly_bias':          25,  # Increased to maintain 100 total
    'bias_4h':              20,
    'smt':                  15,
    'price_action_5m':      20,
    'rr_ratio':             10,
}

# Minimum confidence required to take a trade
MIN_CONFIDENCE = 85

# News confidence penalty
CATEGORY_2_PENALTY = 5  # Caution news reduces confidence by 5 points

# ── LAYER 1: ACCOUNT RISK STATE ──
def check_account_status(account_name, today_loss, total_drawdown):
    """
    Checks if an account is allowed to trade based on drawdown rules.
    Returns a dict with status and reason.
    """
    account = ACCOUNTS[account_name]
    if total_drawdown >= account['total_drawdown_limit']:
        return {
            'can_trade': False,
            'reason': f"Account locked - total drawdown ${total_drawdown} has reached or exceeded ${account['total_drawdown_limit']} limit"
        }
    if today_loss >= account['daily_loss_limit']:
        return {
            'can_trade': False,
            'reason': f"Daily loss limit hit - today's loss ${today_loss} has reached or exceeded ${account['daily_loss_limit']} limit"
        }
    return {
        'can_trade': True,
        'reason': 'Account within risk limits'
    }

# ── LAYER 2: NEWS / CALENDAR CHECK ──
# TEMPORARY: Uses headline scanning from NewsAPI.
# REPLACE WITH: news_engine/ module before live trading.

CATEGORY_1_KEYWORDS = [
    'nonfarm payroll', 'non-farm payroll', 'NFP',
    'federal reserve rate', 'fed rate decision', 'FOMC rate',
    'interest rate decision', 'fed funds rate',
    'consumer price index', 'CPI report', 'core CPI',
    'PCE price index', 'personal consumption expenditure',
    'bank of england rate', 'BoE rate decision', 'MPC rate',
    'ECB rate decision', 'european central bank rate',
    'gross domestic product', 'GDP report'
]

CATEGORY_2_KEYWORDS = [
    'jobless claims', 'unemployment claims',
    'retail sales', 'manufacturing PMI', 'services PMI',
    'trade balance', 'consumer confidence',
    'industrial production', 'PCE inflation',
    'crude oil inventories', 'UoM consumer sentiment',
    'CB leading index', 'flash PMI',
    'UK unemployment', 'claimant count',
    'average earnings', 'UK wages'
]

def check_news_status():
    """
    Checks today's news for Category 1 and Category 2 events.
    Returns a dict with trading permission and reason.
    """
    try:
        articles = get_forex_news()
        all_headlines = ' '.join([
            article['title'].lower() for article in articles
        ])
        for keyword in CATEGORY_1_KEYWORDS:
            if keyword.lower() in all_headlines:
                return {
                    'can_trade': False,
                    'category': 1,
                    'reason': f"Category 1 no-trade event detected: {keyword}",
                    'caution': False
                }
        for keyword in CATEGORY_2_KEYWORDS:
            if keyword.lower() in all_headlines:
                return {
                    'can_trade': True,
                    'category': 2,
                    'reason': f"Category 2 caution event detected: {keyword} — verify it does not fall inside your specific Silver Bullet window",
                    'caution': True
                }
        return {
            'can_trade': True,
            'category': 3,
            'reason': 'No high impact events detected — green light day',
            'caution': False
        }
    except Exception as e:
        return {
            'can_trade': True,
            'category': 2,
            'reason': f"News check failed: {e} — proceed with caution and verify calendar manually",
            'caution': True
        }

# ── LAYER 3: SILVER BULLET TIME WINDOW CHECKER ──

SILVER_BULLET_WINDOWS = {
    'London': {
        'pair': 'EURUSD/GBPUSD',
        'start': dtime(9, 0),
        'end': dtime(10, 0),
    },
    'Gold NY': {
        'pair': 'XAUUSD',
        'start': dtime(13, 30),
        'end': dtime(14, 30),
    },
    'Forex NY': {
        'pair': 'EURUSD/GBPUSD',
        'start': dtime(15, 0),
        'end': dtime(16, 0),
    }
}

def check_silver_bullet_window():
    """
    Checks if the current WAT time falls inside any Silver Bullet window.
    Returns which session is active, or None if outside all windows.
    """
    now = datetime.now(WAT)
    current_time = now.time()
    for session_name, window in SILVER_BULLET_WINDOWS.items():
        if window['start'] <= current_time < window['end']:
            return {
                'active': True,
                'session': session_name,
                'pair': window['pair'],
                'window_start': window['start'].strftime('%H:%M'),
                'window_end': window['end'].strftime('%H:%M'),
                'current_time_wat': now.strftime('%H:%M WAT'),
                'minutes_remaining': int(
                    (datetime.combine(now.date(), window['end']) -
                     now.replace(tzinfo=None)).seconds / 60
                )
            }
    next_window = None
    next_session = None
    for session_name, window in SILVER_BULLET_WINDOWS.items():
        if window['start'] > current_time:
            if next_window is None or window['start'] < next_window:
                next_window = window['start']
                next_session = session_name
    return {
        'active': False,
        'session': None,
        'pair': None,
        'current_time_wat': now.strftime('%H:%M WAT'),
        'next_session': next_session,
        'next_window_opens': next_window.strftime('%H:%M WAT') if next_window else 'No more windows today'
    }

def is_weekend():
    """Checks if today is Saturday or Sunday."""
    now = datetime.now(WAT)
    return now.weekday() in [5, 6]

def is_friday_close():
    """Checks if it is past 22:00 WAT on Friday."""
    now = datetime.now(WAT)
    if now.weekday() == 4 and now.hour >= 22:
        return True
    return False

# ── LAYER 4: LOT SIZE CALCULATOR ──

POINT_VALUES = {
    'EURUSD': 1.0,
    'GBPUSD': 1.0,
    'XAUUSD': 1.0,
}

MIN_LOT = 0.01
MAX_LOT = 0.10

def calculate_lot_size(pair, sl_points, account_name):
    """
    Calculates the correct lot size based on fixed $10 risk
    and actual structural SL distance in points.
    Always rounds DOWN — never rounds up on risk.
    """
    if sl_points <= 0:
        return {
            'valid': False,
            'reason': 'SL distance must be greater than zero'
        }
    if pair not in POINT_VALUES:
        return {
            'valid': False,
            'reason': f'Unknown pair: {pair}. Must be EURUSD, GBPUSD, or XAUUSD'
        }
    account = ACCOUNTS[account_name]
    risk_amount = account['risk_per_trade']
    point_value = POINT_VALUES[pair]
    raw_lot = risk_amount / (sl_points * point_value)
    lot_size = math.floor(raw_lot * 100) / 100
    if lot_size < MIN_LOT:
        return {
            'valid': False,
            'reason': f'Calculated lot size {lot_size} is below minimum {MIN_LOT}. SL distance of {sl_points} points is too wide for $10 risk. Consider skipping this trade.',
            'calculated_lot': lot_size,
            'sl_points': sl_points
        }
    if lot_size > MAX_LOT:
        lot_size = MAX_LOT
    actual_risk = lot_size * sl_points * point_value
    min_tp_points = sl_points * 2
    expected_reward = actual_risk * 2
    return {
        'valid': True,
        'pair': pair,
        'lot_size': lot_size,
        'sl_points': sl_points,
        'min_tp_points': min_tp_points,
        'risk_amount': round(actual_risk, 2),
        'expected_reward': round(expected_reward, 2),
        'r_r_ratio': '1:2 minimum',
        'reason': f'Lot size calculated: {lot_size} lots | Risk: ${round(actual_risk, 2)} | Min TP: {min_tp_points} points'
    }

def verify_rr_ratio(sl_points, tp_points):
    """Verifies that the trade meets the minimum 1:2 R:R requirement."""
    if sl_points <= 0 or tp_points <= 0:
        return {
            'valid': False,
            'reason': 'SL and TP distances must both be greater than zero'
        }
    actual_ratio = tp_points / sl_points
    if actual_ratio < 2.0:
        return {
            'valid': False,
            'actual_ratio': round(actual_ratio, 2),
            'reason': f'R:R ratio is 1:{round(actual_ratio, 2)} — minimum required is 1:2. Adjust TP or skip trade.'
        }
    return {
        'valid': True,
        'actual_ratio': round(actual_ratio, 2),
        'reason': f'R:R ratio verified: 1:{round(actual_ratio, 2)} — meets minimum 1:2 requirement'
    }

# ── CONFIDENCE SCORE CALCULATOR ──

def calculate_confidence(checklist_results, news_caution=False):
    """
    Calculates a confidence score from 0-100 based on weighted rule results.
    Hard stops are not scored — they must pass regardless.
    Trade only if confidence >= 85.
    """
    total_score = 0
    max_possible = sum(w for rule, w in RULE_WEIGHTS.items() if w > 0)
    scored_rules = {}

    for rule, weight in RULE_WEIGHTS.items():
        if weight == 0:
            continue
        if rule not in checklist_results:
            continue
        result = checklist_results[rule]
        if 'passed' in result and result['passed']:
            total_score += weight
            scored_rules[rule] = {
                'weight': weight,
                'earned': weight,
                'passed': True
            }
        else:
            scored_rules[rule] = {
                'weight': weight,
                'earned': 0,
                'passed': False
            }

    # Apply Category 2 news penalty
    if news_caution:
        total_score = max(0, total_score - CATEGORY_2_PENALTY)

    confidence = round((total_score / max_possible) * 100, 1)

    if confidence >= 95:
        grade = 'A+'
        recommendation = 'EXCEPTIONAL SETUP — HIGH CONVICTION TRADE'
    elif confidence >= 90:
        grade = 'A'
        recommendation = 'STRONG SETUP — TAKE THE TRADE'
    elif confidence >= 85:
        grade = 'B'
        recommendation = 'GOOD SETUP — TAKE THE TRADE'
    elif confidence >= 75:
        grade = 'C'
        recommendation = 'MARGINAL SETUP — STAND ASIDE'
    else:
        grade = 'D'
        recommendation = 'WEAK SETUP — DO NOT TRADE'

    return {
        'score': confidence,
        'grade': grade,
        'recommendation': recommendation,
        'meets_threshold': confidence >= MIN_CONFIDENCE,
        'scored_rules': scored_rules,
        'news_caution_applied': news_caution
    }

# ── LAYER 5: TRADE CHECKLIST EVALUATOR ──

def evaluate_checklist(
    account_name,
    today_loss,
    total_drawdown,
    pair,
    direction,
    weekly_bias,
    bias_4h,
    sma_50_slope,
    zone,
    smt_agreement,
    smt_divergence,
    fvg_or_ob,
    liquidity_swept,
    bos_confirmed,
    sl_points,
    tp_points,
):
    """
    Evaluates all checklist conditions from the Silver Bullet strategy.
    ALL hard stops must pass AND confidence must be >= 85.
    """
    results = {}

    # BOX 1: ACCOUNT RISK STATUS
    account_status = check_account_status(account_name, today_loss, total_drawdown)
    results['account_status'] = {
        'passed': account_status['can_trade'],
        'reason': account_status['reason']
    }

    # BOX 2: NEWS CHECK
    news_status = check_news_status()
    results['news_check'] = {
        'passed': news_status['can_trade'],
        'reason': news_status['reason'],
        'caution': news_status.get('caution', False)
    }

    # BOX 3: WEEKEND / FRIDAY CLOSE CHECK
    weekend = is_weekend()
    friday_close = is_friday_close()
    results['market_open'] = {
        'passed': not weekend and not friday_close,
        'reason': 'Weekend — no trading' if weekend else
                  'Friday after 22:00 WAT — markets closing' if friday_close else
                  'Market open — weekday within trading hours'
    }

    # BOX 4: SILVER BULLET WINDOW
    window = check_silver_bullet_window()
    results['silver_bullet_window'] = {
        'passed': window['active'],
        'reason': f"Active session: {window['session']} — {window.get('minutes_remaining', 0)} minutes remaining" if window['active'] else
                  f"Outside Silver Bullet window — next session: {window.get('next_session', 'None')} at {window.get('next_window_opens', 'N/A')}"
    }

    # BOX 5: WEEKLY BIAS
    weekly_bias_valid = weekly_bias in ['bullish', 'bearish']
    weekly_direction_match = (
        (weekly_bias == 'bullish' and direction == 'buy') or
        (weekly_bias == 'bearish' and direction == 'sell')
    )
    results['weekly_bias'] = {
        'passed': weekly_bias_valid and weekly_direction_match,
        'reason': f'Weekly bias is {weekly_bias} — trade direction {direction} {"matches" if weekly_direction_match else "conflicts with"} weekly bias' if weekly_bias_valid else
                  'Weekly bias is ranging — no trade this week'
    }

    # BOX 6: 4H BIAS
    bias_4h_matches_weekly = bias_4h == weekly_bias
    sma_matches_direction = (
        (direction == 'buy' and sma_50_slope == 'up') or
        (direction == 'sell' and sma_50_slope == 'down')
    )
    results['bias_4h'] = {
        'passed': bias_4h_matches_weekly and sma_matches_direction,
        'reason': f'4H bias {bias_4h} {"matches" if bias_4h_matches_weekly else "conflicts with"} weekly bias | SMA 50 slope {sma_50_slope} {"confirms" if sma_matches_direction else "conflicts with"} {direction} direction'
    }

    # BOX 7: PREMIUM / DISCOUNT ZONE
    zone_valid = (
        (direction == 'buy' and zone == 'discount') or
        (direction == 'sell' and zone == 'premium')
    )
    results['zone'] = {
        'passed': zone_valid,
        'reason': f'Price in {zone} zone — {"valid" if zone_valid else "invalid"} for {direction} trade. Never buy in premium. Never sell in discount.'
    }

    # BOX 8: SMT DIVERGENCE
    smt_valid = smt_agreement or smt_divergence
    results['smt'] = {
        'passed': smt_valid,
        'reason': 'SMT confirmed — both pairs agree' if smt_agreement else
                  'SMT divergence signal detected — valid entry signal' if smt_divergence else
                  'SMT invalid — pairs contradict with no clear divergence pattern'
    }

    # BOX 9: 5M PRICE ACTION
    price_action_valid = liquidity_swept and bos_confirmed and fvg_or_ob
    results['price_action_5m'] = {
        'passed': price_action_valid,
        'reason': (
            f'Liquidity sweep: {"✅" if liquidity_swept else "❌"} | '
            f'BOS confirmed: {"✅" if bos_confirmed else "❌"} | '
            f'FVG/OB present: {"✅" if fvg_or_ob else "❌"}'
        )
    }

    # BOX 10: R:R VERIFICATION
    rr = verify_rr_ratio(sl_points, tp_points)
    results['rr_ratio'] = {
        'passed': rr['valid'],
        'reason': rr['reason']
    }

    # LOT SIZE CALCULATION
    lot_calc = calculate_lot_size(pair, sl_points, account_name)
    results['lot_size'] = {
        'valid': lot_calc['valid'],
        'details': lot_calc
    }

    # CONFIDENCE SCORE
    news_caution = results.get('news_check', {}).get('caution', False)
    confidence = calculate_confidence(results, news_caution)

    # FINAL VERDICT
    hard_stops_passed = all([
    results.get('account_status', {}).get('passed', False),
    results.get('market_open', {}).get('passed', False),
    results.get('silver_bullet_window', {}).get('passed', False),
    results.get('news_check', {}).get('passed', False),
    results.get('zone', {}).get('passed', False),  # Added
 ])

    all_passed = hard_stops_passed and confidence['meets_threshold']

    passed_count = sum(
        1 for v in results.values()
        if 'passed' in v and v['passed']
    )
    total_count = sum(
        1 for v in results.values()
        if 'passed' in v
    )

    signal = 'VALID SETUP — LOOK FOR ENTRY' if all_passed else 'INVALID SETUP — STAND ASIDE'

    return {
        'signal': signal,
        'valid': all_passed,
        'passed': passed_count,
        'total': total_count,
        'confidence': confidence['score'],
        'grade': confidence['grade'],
        'recommendation': confidence['recommendation'],
        'pair': pair,
        'direction': direction,
        'account': account_name,
        'lot_size': lot_calc.get('lot_size') if lot_calc['valid'] else None,
        'sl_points': sl_points,
        'tp_points': tp_points,
        'risk_amount': lot_calc.get('risk_amount') if lot_calc['valid'] else None,
        'expected_reward': lot_calc.get('expected_reward') if lot_calc['valid'] else None,
        'checklist': results,
        'confidence_breakdown': confidence['scored_rules'],
        'timestamp': datetime.now(WAT).strftime('%Y-%m-%d %H:%M WAT')
    }

# ── LAYER 6: MAIN BOT FUNCTION ──

def run_bot(
    account_name,
    today_loss,
    total_drawdown,
    pair,
    direction,
    weekly_bias,
    bias_4h,
    sma_50_slope,
    zone,
    smt_agreement,
    smt_divergence,
    fvg_or_ob,
    liquidity_swept,
    bos_confirmed,
    sl_points,
    tp_points
):
    """
    Main entry point for the GOAT trading bot rule engine.
    Runs the complete decision tree from the Silver Bullet strategy.
    Does NOT execute trades yet — that is Session 11.
    """
    print("\n" + "="*60)
    print("GOAT TRADING BOT — RULE ENGINE v2.0")
    print("="*60)
    print(f"Time: {datetime.now(WAT).strftime('%Y-%m-%d %H:%M WAT')}")
    print(f"Account: {account_name} | Pair: {pair} | Direction: {direction.upper()}")
    print("="*60)

    if is_weekend():
        report = {
            'signal': 'NO TRADE — WEEKEND',
            'valid': False,
            'reason': 'Markets closed. No trading Saturday or Sunday.',
            'timestamp': datetime.now(WAT).strftime('%Y-%m-%d %H:%M WAT')
        }
        print(f"\n🔴 {report['signal']}")
        print(f"Reason: {report['reason']}")
        return report

    if is_friday_close():
        report = {
            'signal': 'NO TRADE — FRIDAY CLOSE',
            'valid': False,
            'reason': 'Past 22:00 WAT Friday. Close all positions. Markets closing.',
            'timestamp': datetime.now(WAT).strftime('%Y-%m-%d %H:%M WAT')
        }
        print(f"\n🔴 {report['signal']}")
        print(f"Reason: {report['reason']}")
        return report

    account_status = check_account_status(account_name, today_loss, total_drawdown)
    if not account_status['can_trade']:
        report = {
            'signal': 'NO TRADE — ACCOUNT LOCKED',
            'valid': False,
            'reason': account_status['reason'],
            'timestamp': datetime.now(WAT).strftime('%Y-%m-%d %H:%M WAT')
        }
        print(f"\n🔴 {report['signal']}")
        print(f"Reason: {report['reason']}")
        return report

    news_status = check_news_status()
    if not news_status['can_trade']:
        report = {
            'signal': 'NO TRADE — HIGH IMPACT NEWS',
            'valid': False,
            'reason': news_status['reason'],
            'timestamp': datetime.now(WAT).strftime('%Y-%m-%d %H:%M WAT')
        }
        print(f"\n🔴 {report['signal']}")
        print(f"Reason: {report['reason']}")
        return report

    if news_status.get('caution'):
        print(f"\n🟡 CAUTION: {news_status['reason']}")

    window = check_silver_bullet_window()
    if not window['active']:
        report = {
            'signal': 'NO TRADE — OUTSIDE SILVER BULLET WINDOW',
            'valid': False,
            'reason': f"Current time {window['current_time_wat']} is outside all Silver Bullet windows. Next: {window.get('next_session', 'None')} at {window.get('next_window_opens', 'N/A')}",
            'timestamp': datetime.now(WAT).strftime('%Y-%m-%d %H:%M WAT')
        }
        print(f"\n🔴 {report['signal']}")
        print(f"Reason: {report['reason']}")
        return report

    print(f"\n✅ Inside {window['session']} Silver Bullet window — {window.get('minutes_remaining', 0)} minutes remaining")

    result = evaluate_checklist(
        account_name=account_name,
        today_loss=today_loss,
        total_drawdown=total_drawdown,
        pair=pair,
        direction=direction,
        weekly_bias=weekly_bias,
        bias_4h=bias_4h,
        sma_50_slope=sma_50_slope,
        zone=zone,
        smt_agreement=smt_agreement,
        smt_divergence=smt_divergence,
        fvg_or_ob=fvg_or_ob,
        liquidity_swept=liquidity_swept,
        bos_confirmed=bos_confirmed,
        sl_points=sl_points,
        tp_points=tp_points
    )

    print("\n── CHECKLIST RESULTS ──")
    for check_name, check_result in result['checklist'].items():
        if 'passed' in check_result:
            status = "✅" if check_result['passed'] else "❌"
            print(f"{status} {check_name.upper().replace('_', ' ')}: {check_result['reason']}")

    print(f"\n── CONFIDENCE: {result['confidence']}/100 — Grade {result['grade']} ──")
    print(f"── {result['recommendation']} ──")
    print(f"\n── RESULT: {result['passed']}/{result['total']} checks passed ──")

    if result['valid']:
        print(f"\n🟢 {result['signal']}")
        print(f"Pair: {result['pair']} | Direction: {result['direction'].upper()}")
        print(f"Lot Size: {result['lot_size']} lots")
        print(f"SL: {result['sl_points']} points | TP: {result['tp_points']} points")
        print(f"Risk: ${result['risk_amount']} | Expected Reward: ${result['expected_reward']}")
    else:
        print(f"\n🔴 {result['signal']}")
        print("Failed checks:")
        for check_name, check_result in result['checklist'].items():
            if 'passed' in check_result and not check_result['passed']:
                print(f"  ❌ {check_name.upper().replace('_', ' ')}: {check_result['reason']}")

    print("\n" + "="*60)
    return result


# ── TESTS ──
if __name__ == '__main__':

    print("\n=== TEST 1: VALID SETUP (all conditions met) ===")
    result = evaluate_checklist(
        account_name='Account 2',
        today_loss=0,
        total_drawdown=0,
        pair='EURUSD',
        direction='sell',
        weekly_bias='bearish',
        bias_4h='bearish',
        sma_50_slope='down',
        zone='premium',
        smt_agreement=True,
        smt_divergence=False,
        fvg_or_ob=True,
        liquidity_swept=True,
        bos_confirmed=True,
        sl_points=300,
        tp_points=600
    )
    print(f"\nSIGNAL: {result['signal']}")
    print(f"Confidence: {result['confidence']}/100 — Grade {result['grade']}")
    print(f"Recommendation: {result['recommendation']}")
    print(f"Checks passed: {result['passed']}/{result['total']}")
    if result['valid']:
        print(f"Lot size: {result['lot_size']} lots")
        print(f"Risk: ${result['risk_amount']} | Reward: ${result['expected_reward']}")
    print("\nFailed checks:")
    for check_name, check_result in result['checklist'].items():
        if 'passed' in check_result and not check_result['passed']:
            print(f"  ❌ {check_name}: {check_result['reason']}")

    print("\n=== TEST 2: INVALID SETUP — WRONG ZONE ===")
    result2 = evaluate_checklist(
        account_name='Account 2',
        today_loss=0,
        total_drawdown=0,
        pair='EURUSD',
        direction='sell',
        weekly_bias='bearish',
        bias_4h='bearish',
        sma_50_slope='down',
        zone='discount',
        smt_agreement=True,
        smt_divergence=False,
        fvg_or_ob=True,
        liquidity_swept=True,
        bos_confirmed=True,
        sl_points=300,
        tp_points=600
    )
    print(f"\nSIGNAL: {result2['signal']}")
    print(f"Confidence: {result2['confidence']}/100 — Grade {result2['grade']}")
    print(f"Recommendation: {result2['recommendation']}")
    print(f"Checks passed: {result2['passed']}/{result2['total']}")
    print("\nFailed checks:")
    for check_name, check_result in result2['checklist'].items():
        if 'passed' in check_result and not check_result['passed']:
            print(f"  ❌ {check_name}: {check_result['reason']}")

    print("\n=== TEST 3: ACCOUNT LOCKED ===")
    result3 = evaluate_checklist(
        account_name='Account 2',
        today_loss=0,
        total_drawdown=50,
        pair='EURUSD',
        direction='sell',
        weekly_bias='bearish',
        bias_4h='bearish',
        sma_50_slope='down',
        zone='premium',
        smt_agreement=True,
        smt_divergence=False,
        fvg_or_ob=True,
        liquidity_swept=True,
        bos_confirmed=True,
        sl_points=300,
        tp_points=600
    )
    print(f"\nSIGNAL: {result3['signal']}")
    print(f"Confidence: {result3['confidence']}/100 — Grade {result3['grade']}")
    print(f"Recommendation: {result3['recommendation']}")
    print(f"Checks passed: {result3['passed']}/{result3['total']}")
    print("\nFailed checks:")
    for check_name, check_result in result3['checklist'].items():
        if 'passed' in check_result and not check_result['passed']:
            print(f"  ❌ {check_name}: {check_result['reason']}")
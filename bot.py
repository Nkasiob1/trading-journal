# bot.py
# GOAT Trading Bot - Rule Engine
# Built strictly according to documented Silver Bullet strategy

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

# ── LAYER 1: ACCOUNT RISK STATE ──
def check_account_status(account_name, today_loss, total_drawdown):
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
    now = datetime.now(WAT)
    return now.weekday() in [5, 6]

def is_friday_close():
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

    # FINAL VERDICT
    all_passed = all(
        v['passed'] for v in results.values()
        if 'passed' in v
    ) and lot_calc['valid']

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
        'pair': pair,
        'direction': direction,
        'account': account_name,
        'lot_size': lot_calc.get('lot_size') if lot_calc['valid'] else None,
        'sl_points': sl_points,
        'tp_points': tp_points,
        'risk_amount': lot_calc.get('risk_amount') if lot_calc['valid'] else None,
        'expected_reward': lot_calc.get('expected_reward') if lot_calc['valid'] else None,
        'checklist': results,
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
    print("\n" + "="*60)
    print("GOAT TRADING BOT — RULE ENGINE")
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
    print(f"Checks passed: {result3['passed']}/{result3['total']}")
    print("\nFailed checks:")
    for check_name, check_result in result3['checklist'].items():
        if 'passed' in check_result and not check_result['passed']:
            print(f"  ❌ {check_name}: {check_result['reason']}")
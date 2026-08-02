# live_trader.py
# GOAT Live Execution -- v3.0, Mean-Reversion engine added
#
# v3.0 CHANGE: added the mean-reversion engine (mean_reversion.py) -- three independent
# strategies (Bollinger+RSI14, RSI2, VWAP deviation) running on all 7 instruments, every
# loop iteration, completely independent of the ICT engine's Silver Bullet windows.
# Tagged with its own magic number (MR_MAGIC) so it's tracked separately in the journal
# and has its OWN kill switch counter -- a losing streak in one engine should not wrongly
# pause the other, same reasoning as why manual trades stay separate from bot trades.
#
# REAL DESIGN CHOICES, stated plainly:
#   - Fixed $4.00 risk per trade for mean reversion (not the ICT engine's PAIR_RISK table)
#     -- this exact number is what was backtested and validated, do not change casually
#   - NO one-trade-per-pair lock for mean reversion -- multiple overlapping positions on
#     the same instrument are allowed. This matches exactly what was backtested (the
#     $1,000/quarter, 75% hit-rate result). Your account is in Hedge mode, so this is
#     technically supported.
#   - Account-wide MAX_LOSS_PCT tightened to 9% (in bot.py) -- applies to BOTH engines,
#     since it's one real account with one real drawdown floor
#   - Real FTMO news blackout calendar stays a hard requirement for mean reversion too
#   - Added has_opposing_position() -- stops either engine from opening a trade AGAINST
#     a position the other engine already holds on the same instrument. Same-direction
#     overlap (both engines agreeing) is still allowed.
#
# v2.2 CHANGE (kept): bos_window=12 for the ICT engine (backtested best single change:
# 321 trades, +$10,451.74 vs +$8,556.99 at bos_window=6). Rejection-distance logging on
# every pending sweep. Persistent CSV logging (signal_evaluations.csv) of every ICT
# signal evaluated, pass or fail.
#
# v2.1 CHANGE (kept): fixed the ICT engine's SMT tautology bug -- smt_divergence now
# requires the other pair to have ACTUALLY confirmed something, not just "no data".
#
# v2.0 CHANGE (kept): EURUSD, XAUUSD, DE40 scan continuously for the ICT engine (no
# window restriction). GBPUSD, US500, USTEC, US30 keep window-gated behavior.
#
# DRY_RUN = False -- real order placement is live on the FTMO demo account.

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import json
import time
import csv
import os
from datetime import datetime, date
import pytz
import bot
import mean_reversion as mr
import database
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

DRY_RUN = False

WAT = pytz.timezone('Africa/Lagos')
CET = pytz.timezone('Europe/Prague')

STATE_FILE = 'goat_state.json'
BOT_MAGIC = 234000       # ICT engine
MR_MAGIC = 234001        # Mean-reversion engine -- separate, so journal/kill-switch don't cross-contaminate

SYMBOL_MAP = {
    'EURUSD': 'EURUSD', 'GBPUSD': 'GBPUSD', 'XAUUSD': 'XAUUSD',
    'USTEC': 'US100.cash', 'US30': 'US30.cash', 'US500': 'US500.cash', 'DE40': 'GER40.cash',
}

PAIR_SESSIONS = {
    'GBPUSD': ['Asian KZ', 'London Open KZ', 'London', 'Forex NY'],
    'USTEC':  ['NASDAQ PM'],
    'US30':   ['NASDAQ PM'],
    'US500':  ['NASDAQ PM'],
}

NO_WINDOW_PAIRS = ['EURUSD', 'XAUUSD', 'DE40']

POINT_SCALE = {'EURUSD': 100000, 'GBPUSD': 100000, 'XAUUSD': 100,
                'USTEC': 1, 'US30': 1, 'US500': 1, 'DE40': 1}

price_action_tracking = {}

REJECTION_LOG_FILE = 'signal_evaluations.csv'
MR_LOG_FILE = 'mean_reversion_signals.csv'


def load_state():
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            'daily_closing_balances': {},
            'daily_pnl_by_date': {},
            'bot_consecutive_losses': 0,
            'last_bot_loss_ts': None,
            'mr_consecutive_losses': 0,
            'last_mr_loss_ts': None,
            'last_seen_cet_date': None,
            'last_processed_deal_ticket': 0,
            'open_bot_positions': {},
            'open_mr_positions': {},
        }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def select_all_symbols():
    for pair, symbol in SYMBOL_MAP.items():
        if not mt5.symbol_select(symbol, True):
            print(f"[WARNING] Could not select symbol {symbol} ({pair}) -- check it exists on this account")


def handle_daily_rollover(state):
    now_cet_date = str(datetime.now(CET).date())
    if state['last_seen_cet_date'] != now_cet_date:
        account_info = mt5.account_info()
        if state['last_seen_cet_date'] is not None:
            state['daily_closing_balances'][state['last_seen_cet_date']] = account_info.balance
        state['last_seen_cet_date'] = now_cet_date
        print(f"[ROLLOVER] New CET trading day: {now_cet_date}")
    return state


def get_recent_bars(symbol, n=300):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, n)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.set_index('time')
    df = df.rename(columns={'tick_volume': 'tickvol'})
    cols = ['open', 'high', 'low', 'close']
    if 'tickvol' in df.columns:
        cols.append('tickvol')
    return df[cols]

def compute_weekly_bias(symbol):
    weekly_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_W1, 0, 10)
    if weekly_rates is None or len(weekly_rates) < 3:
        return 'ranging'
    closes = [bar['close'] for bar in weekly_rates]
    if closes[-2] > closes[-3]:
        return 'bullish'
    elif closes[-2] < closes[-3]:
        return 'bearish'
    return 'ranging'

def compute_4h_bias_and_slope(symbol):
    h4_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 60)
    if h4_rates is None or len(h4_rates) < 51:
        return 'ranging', 'flat'
    closes = [bar['close'] for bar in h4_rates]
    bias = 'bullish' if closes[-1] > closes[-2] else 'bearish'
    sma50_now = sum(closes[-50:]) / 50
    sma50_prev = sum(closes[-51:-1]) / 50
    slope = 'up' if sma50_now > sma50_prev else 'down'
    return bias, slope

def compute_zone(df):
    week_start = df.index.to_period('W').start_time
    tmp = pd.DataFrame({'high': df['high'], 'low': df['low'], 'week_start': week_start})
    running_high = tmp.groupby('week_start')['high'].cummax()
    running_low = tmp.groupby('week_start')['low'].cummin()
    mid = (running_high.iloc[-1] + running_low.iloc[-1]) / 2
    return 'discount' if df['close'].iloc[-1] < mid else 'premium'


def update_price_action_state(pair, df, tracking, lookback=12, bos_window=12, allow_new_sweep=True):
    highs, lows, closes = df['high'].values, df['low'].values, df['close'].values
    n = len(df)
    if n < lookback + 3:
        return None
    i = n - 1
    current_bar_time = df.index[i]

    if pair not in tracking:
        tracking[pair] = {'last_bar_time': None, 'pending': None}

    if tracking[pair]['last_bar_time'] == current_bar_time:
        return None
    tracking[pair]['last_bar_time'] = current_bar_time

    pending = tracking[pair]['pending']

    if pending is not None:
        if pending['direction'] == 'buy' and closes[i] > pending['recent_high']:
            tracking[pair]['pending'] = None
            return {'confirmed': True, 'direction': 'buy', 'swing_low': pending['recent_low'],
                    'swing_high': pending['recent_high'], 'fvg_or_ob': pending['fvg_or_ob']}
        if pending['direction'] == 'sell' and closes[i] < pending['recent_low']:
            tracking[pair]['pending'] = None
            return {'confirmed': True, 'direction': 'sell', 'swing_low': pending['recent_low'],
                    'swing_high': pending['recent_high'], 'fvg_or_ob': pending['fvg_or_ob']}

        if pending['direction'] == 'buy':
            distance = pending['recent_high'] - closes[i]
            print(f"  {pair} BUY pending | Close={closes[i]:.5f} Need>{pending['recent_high']:.5f} "
                  f"(short by {distance:.5f})")
        if pending['direction'] == 'sell':
            distance = closes[i] - pending['recent_low']
            print(f"  {pair} SELL pending | Close={closes[i]:.5f} Need<{pending['recent_low']:.5f} "
                  f"(short by {distance:.5f})")

        pending['bars_elapsed'] += 1
        if pending['bars_elapsed'] >= bos_window:
            tracking[pair]['pending'] = None
        return None

    if not allow_new_sweep:
        return None

    recent_low = lows[i-lookback:i].min()
    recent_high = highs[i-lookback:i].max()
    sweep_buy = lows[i] < recent_low and closes[i] > recent_low
    sweep_sell = highs[i] > recent_high and closes[i] < recent_high
    fvg_bull = any(lows[j] > highs[j-2] for j in range(max(2, i-6), i+1))
    fvg_bear = any(highs[j] < lows[j-2] for j in range(max(2, i-6), i+1))

    if sweep_buy:
        tracking[pair]['pending'] = {'direction': 'buy', 'recent_high': recent_high,
                                       'recent_low': recent_low, 'bars_elapsed': 0, 'fvg_or_ob': fvg_bull}
    elif sweep_sell:
        tracking[pair]['pending'] = {'direction': 'sell', 'recent_high': recent_high,
                                       'recent_low': recent_low, 'bars_elapsed': 0, 'fvg_or_ob': fvg_bear}
    return None


def log_signal_evaluation(pair, ts, direction, result):
    checklist = result['checklist']
    file_exists = os.path.isfile(REJECTION_LOG_FILE)
    row = {
        'timestamp': ts.strftime('%Y-%m-%d %H:%M:%S'), 'pair': pair, 'direction': direction,
        'confidence': result['confidence'], 'valid': result['valid'],
        'account_status': checklist.get('account_status', {}).get('passed'),
        'news_check': checklist.get('news_check', {}).get('passed'),
        'market_open': checklist.get('market_open', {}).get('passed'),
        'silver_bullet_window': checklist.get('silver_bullet_window', {}).get('passed'),
        'weekly_bias': checklist.get('weekly_bias', {}).get('passed'),
        'bias_4h': checklist.get('bias_4h', {}).get('passed'),
        'zone': checklist.get('zone', {}).get('passed'),
        'smt': checklist.get('smt', {}).get('passed'),
        'price_action_5m': checklist.get('price_action_5m', {}).get('passed'),
        'rr_ratio': checklist.get('rr_ratio', {}).get('passed'),
        'rejected_because': '; '.join([
            label for key, label in
            [('account_status','Account'),('news_check','News'),('market_open','Market Open'),
             ('silver_bullet_window','Window'),('weekly_bias','Weekly Bias'),('bias_4h','4H Bias'),
             ('zone','Zone'),('smt','SMT'),('price_action_5m','Price Action'),('rr_ratio','RR')]
            if key in checklist and not checklist[key].get('passed', False)
        ]),
    }
    with open(REJECTION_LOG_FILE, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def log_mr_signal(pair, ts, strategy, direction, result):
    file_exists = os.path.isfile(MR_LOG_FILE)
    checklist = result['checklist']
    row = {
        'timestamp': ts.strftime('%Y-%m-%d %H:%M:%S'), 'pair': pair, 'strategy': strategy,
        'direction': direction, 'valid': result['valid'],
        'account_status': checklist.get('account_status', {}).get('passed'),
        'news_check': checklist.get('news_check', {}).get('passed'),
        'market_open': checklist.get('market_open', {}).get('passed'),
        'lot_valid': checklist.get('lot_size', {}).get('valid'),
    }
    with open(MR_LOG_FILE, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def has_opposing_position(symbol, my_magic, my_direction):
    """Prevents ICT and mean-reversion from fighting each other -- blocks a new trade only
    if the OTHER engine already has an OPPOSITE-direction position open on this symbol.
    Same-direction overlap (both engines agreeing) is allowed; so is no conflict at all."""
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return False
    for p in positions:
        if p.magic != my_magic:
            other_direction = 'buy' if p.type == mt5.ORDER_TYPE_BUY else 'sell'
            if other_direction != my_direction:
                return True
    return False


def save_signal_chart(df, pair, direction, entry_price, sl_price, tp_price, confidence, label=""):
    fig, ax = plt.subplots(figsize=(12, 6))
    recent = df.tail(100)
    ax.plot(recent.index, recent['close'], color='white', linewidth=1)
    ax.axhline(entry_price, color='yellow', linestyle='--', label=f'Entry {entry_price:.5f}')
    ax.axhline(sl_price, color='red', linestyle='--', label=f'SL {sl_price:.5f}')
    ax.axhline(tp_price, color='green', linestyle='--', label=f'TP {tp_price:.5f}')
    title = f'{pair} {direction.upper()} signal'
    if confidence is not None:
        title += f' -- confidence {confidence}'
    if label:
        title = f'[{label}] ' + title
    ax.set_title(title)
    ax.set_facecolor('black')
    fig.patch.set_facecolor('black')
    ax.tick_params(colors='white')
    ax.legend()
    filename = f'signal_{pair}_{label}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
    fig.savefig(filename, facecolor='black')
    plt.close(fig)
    print(f"  [CHART] Saved: {filename}")


def process_confirmed_signal(pair, symbol, df, bos_result, session_name, state,
                              current_equity, daily_floor, max_loss_floor, forex_confirmed_cache):
    weekly_bias = compute_weekly_bias(symbol)
    bias_4h, sma_slope = compute_4h_bias_and_slope(symbol)
    zone = compute_zone(df)
    direction = bos_result['direction']

    profile = bot.get_pair_profile(pair)
    if profile['trend_required']:
        expected_direction = 'buy' if weekly_bias == 'bullish' else 'sell' if weekly_bias == 'bearish' else None
        if expected_direction != direction:
            print(f"[{pair}] BOS confirmed {direction} but weekly bias is {weekly_bias} -- skipping (trend required)")
            return

    sl_price_dist = abs(bos_result['swing_high'] - bos_result['swing_low'])
    if sl_price_dist <= 0:
        return
    sl_points = round(sl_price_dist * POINT_SCALE[pair])
    tp_points = sl_points * 2

    if pair in ('EURUSD', 'GBPUSD'):
        other_pair = 'GBPUSD' if pair == 'EURUSD' else 'EURUSD'
        other_result = forex_confirmed_cache.get(other_pair)
        smt_agreement = other_result is not None and other_result['direction'] == direction
        smt_divergence = other_result is not None and other_result['direction'] != direction
    else:
        smt_agreement, smt_divergence = True, False

    result = bot.evaluate_checklist(
        current_equity=current_equity, daily_floor=daily_floor, max_loss_floor=max_loss_floor,
        pair=pair, direction=direction, weekly_bias=weekly_bias, bias_4h=bias_4h,
        sma_50_slope=sma_slope, zone=zone, smt_agreement=smt_agreement,
        smt_divergence=smt_divergence, fvg_or_ob=bos_result['fvg_or_ob'],
        liquidity_swept=True, bos_confirmed=True,
        sl_points=sl_points, tp_points=tp_points,
    )

    print(f"[ICT][{pair}] {direction.upper()} CONFIRMED BOS | confidence={result['confidence']} | valid={result['valid']}")
    log_signal_evaluation(pair, df.index[-1], direction, result)
    checklist = result['checklist']
    check_labels = {
        'account_status': 'Account', 'news_check': 'News', 'market_open': 'Market Open',
        'silver_bullet_window': 'Window', 'weekly_bias': 'Weekly Bias', 'bias_4h': '4H Bias',
        'zone': 'Zone', 'smt': 'SMT', 'price_action_5m': 'Price Action', 'rr_ratio': 'RR',
    }
    failed_items = []
    line_parts = []
    for key, label in check_labels.items():
        if key in checklist:
            passed = checklist[key].get('passed', False)
            mark = '\u2713' if passed else '\u2717'
            line_parts.append(f"{label} {mark}")
            if not passed:
                failed_items.append(label)
    print(f"  {' | '.join(line_parts)}")
    if failed_items:
        print(f"  Rejected because: {', '.join(failed_items)}")

    if result['valid']:
        if has_opposing_position(symbol, BOT_MAGIC, direction):
            print(f"  [SKIPPED] Mean-reversion already holds an opposite-direction position on {pair} -- not opening ICT trade against it")
            return

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            print(f"  [ERROR] No live tick for {symbol} -- skipping")
            return

        entry_price = tick.ask if direction == 'buy' else tick.bid
        sl_price = entry_price - sl_price_dist if direction == 'buy' else entry_price + sl_price_dist
        tp_price = entry_price + sl_price_dist * 2 if direction == 'buy' else entry_price - sl_price_dist * 2

        print(f"  >>> ICT SIGNAL: {pair} {direction} | lot={result['lot_size']} | "
              f"SL={sl_price:.5f} TP={tp_price:.5f} | risking ${result['risk_amount']}")

        save_signal_chart(df, pair, direction, entry_price, sl_price, tp_price, result['confidence'], label="ICT")

        if not DRY_RUN:
            order = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": result['lot_size'],
                "type": mt5.ORDER_TYPE_BUY if direction == 'buy' else mt5.ORDER_TYPE_SELL,
                "price": entry_price, "sl": sl_price, "tp": tp_price, "deviation": 20,
                "magic": BOT_MAGIC, "comment": "GOAT-ICT", "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            })
            print(f"  ORDER RESULT: {order}")
            if order is not None and order.retcode == mt5.TRADE_RETCODE_DONE:
                if 'open_bot_positions' not in state:
                    state['open_bot_positions'] = {}
                state['open_bot_positions'][str(order.order)] = {
                    'pair': pair, 'session': session_name, 'entry': entry_price,
                    'sl': sl_price, 'tp': tp_price, 'risk_amount': result['risk_amount'],
                    'confidence': result['confidence'],
                }
        else:
            print("  (DRY RUN -- no order placed, nothing logged)")


def process_mr_signal(pair, symbol, df, sig, state, current_equity, daily_floor, max_loss_floor):
    """Mean-reversion signal handler -- deliberately independent of the ICT engine's logic."""
    direction = sig['direction']
    strategy = sig['strategy']
    atr = sig['atr']
    sl_dist = atr * mr.SL_ATR_MULT
    tp_dist = sl_dist * mr.TP_ATR_MULT   # true 3:1, per the corrected math (risk $4 -> gain $12)

    result = bot.evaluate_mean_reversion_signal(
        current_equity=current_equity, daily_floor=daily_floor, max_loss_floor=max_loss_floor,
        pair=pair, direction=direction, sl_dist=sl_dist,
        point_scale=POINT_SCALE[pair], point_value=bot.POINT_VALUES[pair],
    )

    print(f"[MR][{pair}] {strategy} {direction.upper()} | valid={result['valid']}")
    log_mr_signal(pair, df.index[-1], strategy, direction, result)
    if not result['valid']:
        failed = [k for k, v in result['checklist'].items() if isinstance(v, dict) and 'passed' in v and not v['passed']]
        if failed:
            print(f"  Rejected because: {', '.join(failed)}")
        return

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"  [ERROR] No live tick for {symbol} -- skipping")
        return

    entry_price = tick.ask if direction == 'buy' else tick.bid
    if direction == 'buy':
        sl_price = entry_price - sl_dist
        tp_price = entry_price + tp_dist
    else:
        sl_price = entry_price + sl_dist
        tp_price = entry_price - tp_dist

    print(f"  >>> MR SIGNAL: {pair} {strategy} {direction} | lot={result['lot_size']} | "
          f"SL={sl_price:.5f} TP={tp_price:.5f} | risking ${result['risk_amount']}")

    if has_opposing_position(symbol, MR_MAGIC, direction):
        print(f"  [SKIPPED] ICT engine already holds an opposite-direction position on {pair} -- not opening MR trade against it")
        return

    save_signal_chart(df, pair, direction, entry_price, sl_price, tp_price, None, label=f"MR-{strategy}")

    if not DRY_RUN:
        order = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": result['lot_size'],
            "type": mt5.ORDER_TYPE_BUY if direction == 'buy' else mt5.ORDER_TYPE_SELL,
            "price": entry_price, "sl": sl_price, "tp": tp_price, "deviation": 20,
            "magic": MR_MAGIC, "comment": f"GOAT-MR-{strategy}", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        })
        print(f"  ORDER RESULT: {order}")
        if order is not None and order.retcode == mt5.TRADE_RETCODE_DONE:
            if 'open_mr_positions' not in state:
                state['open_mr_positions'] = {}
            state['open_mr_positions'][str(order.order)] = {
                'pair': pair, 'strategy': strategy, 'entry': entry_price,
                'sl': sl_price, 'tp': tp_price, 'risk_amount': result['risk_amount'],
            }
    else:
        print("  (DRY RUN -- no order placed, nothing logged)")


def process_new_closed_deals(state):
    from_date = datetime(2020, 1, 1)
    to_date = datetime.now() + pd.Timedelta(days=1)
    deals = mt5.history_deals_get(from_date, to_date)
    if deals is None:
        return state

    for deal in deals:
        if deal.ticket <= state['last_processed_deal_ticket']:
            continue
        if deal.entry != 1:
            continue

        pnl = deal.profit
        deal_date_cet = str(datetime.fromtimestamp(deal.time).astimezone(CET).date())
        state['daily_pnl_by_date'][deal_date_cet] = state['daily_pnl_by_date'].get(deal_date_cet, 0) + pnl

        if deal.magic == BOT_MAGIC:
            if pnl < 0:
                state['bot_consecutive_losses'] += 1
                state['last_bot_loss_ts'] = datetime.now(WAT).isoformat()
                print(f"[ICT TRADE CLOSED] Loss: ${pnl:.2f} -- ICT consecutive losses now {state['bot_consecutive_losses']}")
            elif pnl > 0:
                state['bot_consecutive_losses'] = 0
                print(f"[ICT TRADE CLOSED] Win: ${pnl:.2f} -- ICT consecutive losses reset")

            position_key = str(deal.position_id)
            trade_info = state.get('open_bot_positions', {}).pop(position_key, None)
            if trade_info is not None:
                risk_amount = trade_info['risk_amount']
                r_multiple = round(pnl / risk_amount, 2) if risk_amount else 0
                result_label = 'WIN' if pnl > 0 else 'LOSS'
                database.save_trade(
                    pair=trade_info['pair'], session=trade_info['session'], entry=trade_info['entry'],
                    stop_loss=trade_info['sl'], take_profit=trade_info['tp'], result=result_label,
                    r_multiple=r_multiple, account='FTMO Account',
                    date=datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M'),
                    notes=f"GOAT-ICT auto-trade | confidence={trade_info.get('confidence', 'N/A')}",
                )
                print(f"  [JOURNAL] Logged: {trade_info['pair']} {result_label} ({r_multiple}R)")
            else:
                print(f"  [WARNING] ICT trade closed but no matching open-trade record found")

        elif deal.magic == MR_MAGIC:
            if pnl < 0:
                state['mr_consecutive_losses'] += 1
                state['last_mr_loss_ts'] = datetime.now(WAT).isoformat()
                print(f"[MR TRADE CLOSED] Loss: ${pnl:.2f} -- MR consecutive losses now {state['mr_consecutive_losses']}")
            elif pnl > 0:
                state['mr_consecutive_losses'] = 0
                print(f"[MR TRADE CLOSED] Win: ${pnl:.2f} -- MR consecutive losses reset")

            position_key = str(deal.position_id)
            trade_info = state.get('open_mr_positions', {}).pop(position_key, None)
            if trade_info is not None:
                risk_amount = trade_info['risk_amount']
                r_multiple = round(pnl / risk_amount, 2) if risk_amount else 0
                result_label = 'WIN' if pnl > 0 else 'LOSS'
                database.save_trade(
                    pair=trade_info['pair'], session=f"MeanReversion-{trade_info['strategy']}",
                    entry=trade_info['entry'], stop_loss=trade_info['sl'], take_profit=trade_info['tp'],
                    result=result_label, r_multiple=r_multiple, account='FTMO Account',
                    date=datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M'),
                    notes=f"GOAT-MR auto-trade | strategy={trade_info['strategy']}",
                )
                print(f"  [JOURNAL] Logged: {trade_info['pair']} MR-{trade_info['strategy']} {result_label} ({r_multiple}R)")
            else:
                print(f"  [WARNING] MR trade closed but no matching open-trade record found")

        else:
            print(f"[MANUAL TRADE CLOSED] P&L: ${pnl:.2f} -- counted toward account P&L, not any bot kill switch")

        state['last_processed_deal_ticket'] = max(state['last_processed_deal_ticket'], deal.ticket)

    return state


def main():
    if not mt5.initialize():
        print("FAILED to connect to MT5:", mt5.last_error())
        return
    print(f"Connected to MT5. DRY_RUN = {DRY_RUN}")
    if DRY_RUN:
        print(">>> DRY RUN MODE -- no real orders will be placed, nothing will be logged. <<<")

    database.init_db()
    select_all_symbols()
    state = load_state()
    for key in ['mr_consecutive_losses', 'last_mr_loss_ts', 'open_mr_positions']:
        if key not in state:
            state[key] = 0 if 'losses' in key else (None if 'ts' in key else {})

    try:
        while True:
            now_wat = datetime.now(WAT)

            if bot.is_weekend(now_wat):
                print(f"[{now_wat.strftime('%H:%M WAT')}] Weekend -- market closed, sleeping 10 min.")
                time.sleep(600)
                continue

            state = handle_daily_rollover(state)
            state = process_new_closed_deals(state)

            account_info = mt5.account_info()
            current_equity = account_info.equity

            daily_floor, max_loss_floor = bot.compute_daily_floors(
                {date.fromisoformat(k): v for k, v in state['daily_closing_balances'].items()},
                bot.INITIAL_CAPITAL
            )

            acc_status = bot.check_account_status(current_equity, daily_floor, max_loss_floor)
            if not acc_status['can_trade']:
                print(f"[BLOCKED -- ACCOUNT WIDE] {acc_status['reason']}")
                save_state(state)
                time.sleep(60)
                continue

            # ── ICT engine kill switch (own counter) ──
            last_loss_ts = datetime.fromisoformat(state['last_bot_loss_ts']) if state['last_bot_loss_ts'] else None
            ict_kill = bot.check_kill_switch(state['bot_consecutive_losses'], last_loss_ts)
            ict_paused = ict_kill['triggered']
            if ict_paused:
                print(f"[ICT KILL SWITCH] {ict_kill['reason']}")

            # ── Mean-reversion kill switch (own, separate counter) ──
            last_mr_loss_ts = datetime.fromisoformat(state['last_mr_loss_ts']) if state['last_mr_loss_ts'] else None
            mr_kill = bot.check_kill_switch(state['mr_consecutive_losses'], last_mr_loss_ts)
            mr_paused = mr_kill['triggered']
            if mr_paused:
                print(f"[MR KILL SWITCH] {mr_kill['reason']}")

            forex_confirmed_cache = {}

            # ══════════════════ ICT ENGINE ══════════════════
            if not ict_paused:
                for pair in NO_WINDOW_PAIRS:
                    symbol = SYMBOL_MAP[pair]
                    positions = mt5.positions_get(symbol=symbol)
                    if positions and any(p.magic == BOT_MAGIC for p in positions):
                        continue
                    df = get_recent_bars(symbol)
                    if df is None or len(df) < 100:
                        print(f"[{pair}] Not enough price data yet, skipping")
                        continue
                    bos_result = update_price_action_state(pair, df, price_action_tracking, allow_new_sweep=True)
                    if pair == 'EURUSD' and bos_result is not None:
                        forex_confirmed_cache['EURUSD'] = bos_result
                    if bos_result is not None:
                        process_confirmed_signal(pair, symbol, df, bos_result, 'continuous',
                                                  state, current_equity, daily_floor, max_loss_floor, forex_confirmed_cache)
                    else:
                        pending = price_action_tracking.get(pair, {}).get('pending')
                        status = f"tracking pending {pending['direction']} sweep (bar {pending['bars_elapsed']}/12)" if pending else "no sweep detected"
                        print(f"[ICT][{now_wat.strftime('%H:%M')}] {pair}: {status}")

                window = bot.check_silver_bullet_window()
                session_name = window['session'] if window['active'] else None
                pairs_this_session = [p for p, s in PAIR_SESSIONS.items() if session_name and session_name in s]
                already_handled = set()

                pairs_with_pending = [p for p, t in price_action_tracking.items()
                                       if t.get('pending') is not None and p in PAIR_SESSIONS]
                for pair in pairs_with_pending:
                    symbol = SYMBOL_MAP[pair]
                    positions = mt5.positions_get(symbol=symbol)
                    if positions and any(p.magic == BOT_MAGIC for p in positions):
                        continue
                    df = get_recent_bars(symbol)
                    if df is None or len(df) < 100:
                        continue
                    bos_result = update_price_action_state(pair, df, price_action_tracking, allow_new_sweep=False)
                    already_handled.add(pair)
                    if pair == 'GBPUSD' and bos_result is not None:
                        forex_confirmed_cache['GBPUSD'] = bos_result
                    if bos_result is not None:
                        process_confirmed_signal(pair, symbol, df, bos_result, session_name or 'post-window',
                                                  state, current_equity, daily_floor, max_loss_floor, forex_confirmed_cache)
                    else:
                        pending = price_action_tracking.get(pair, {}).get('pending')
                        status = f"tracking pending {pending['direction']} sweep (bar {pending['bars_elapsed']}/12)" if pending else "sweep resolved/expired"
                        print(f"[ICT][{now_wat.strftime('%H:%M')}] {pair}: {status}")

                if window['active']:
                    for pair in pairs_this_session:
                        if pair in already_handled:
                            continue
                        symbol = SYMBOL_MAP[pair]
                        positions = mt5.positions_get(symbol=symbol)
                        if positions and any(p.magic == BOT_MAGIC for p in positions):
                            continue
                        df = get_recent_bars(symbol)
                        if df is None or len(df) < 100:
                            print(f"[{pair}] Not enough price data yet, skipping")
                            continue
                        bos_result = update_price_action_state(pair, df, price_action_tracking, allow_new_sweep=True)
                        if pair == 'GBPUSD' and bos_result is not None:
                            forex_confirmed_cache['GBPUSD'] = bos_result
                        if bos_result is not None:
                            process_confirmed_signal(pair, symbol, df, bos_result, session_name,
                                                      state, current_equity, daily_floor, max_loss_floor, forex_confirmed_cache)
                        else:
                            pending = price_action_tracking.get(pair, {}).get('pending')
                            status = f"tracking pending {pending['direction']} sweep (bar {pending['bars_elapsed']}/12)" if pending else "no sweep detected"
                            print(f"[ICT][{now_wat.strftime('%H:%M')}] {pair}: {status}")

            # ══════════════════ MEAN REVERSION ENGINE ══════════════════
            # All 7 pairs, every iteration, no session windows -- independent of the ICT engine.
            # No one-trade-per-pair lock, by design (see header note).
            if not mr_paused:
                for pair, symbol in SYMBOL_MAP.items():
                    df_mr = get_recent_bars(symbol, n=300)
                    if df_mr is None or len(df_mr) < 205:
                        continue
                    df_mr = mr.compute_indicators(df_mr)
                    signals = mr.check_signal(df_mr)
                    for sig in signals:
                        process_mr_signal(pair, symbol, df_mr, sig, state, current_equity, daily_floor, max_loss_floor)
                    if not signals:
                        pass  # quiet -- MR doesn't print a "no signal" heartbeat for all 7 pairs every minute, too noisy

            save_state(state)
            time.sleep(60)

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        save_state(state)
        mt5.shutdown()


if __name__ == '__main__':
    main()
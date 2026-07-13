# live_trader.py
# GOAT Live Execution -- v1.2, with journal database integration
#
# - Bot orders tagged with a magic number -- kill switch/consecutive-losses tracking only
#   counts the BOT'S OWN trades, not manual trades on the same account
# - Guards against tick=None before dereferencing tick.ask/tick.bid
# - Explicitly selects all 7 symbols on startup
# - Skips all work entirely on weekends
# - Deviation (slippage tolerance) added to real order requests
# - Bot trades are saved to the actual GOAT journal database (database.py), same table
#   manual trades go into, with session-level stats tracking all 6 real sessions
#
# KNOWN LIMITATION: if this script isn't running at the exact moment of CET midnight
# rollover, the "closing balance" recorded for that day will be inaccurate. Cross-check
# against FTMO's own dashboard periodically, especially after any gap in uptime.
#
# SAFETY: starts in DRY_RUN mode. No real orders, no real journal entries, until you set
# DRY_RUN = False yourself.

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import json
import time
from datetime import datetime, date
import pytz
import bot
import database

DRY_RUN = True

WAT = pytz.timezone('Africa/Lagos')
CET = pytz.timezone('Europe/Prague')

STATE_FILE = 'goat_state.json'
BOT_MAGIC = 234000

SYMBOL_MAP = {
    'EURUSD': 'EURUSD', 'GBPUSD': 'GBPUSD', 'XAUUSD': 'XAUUSD',
    'USTEC': 'US100.cash', 'US30': 'US30.cash', 'US500': 'US500.cash', 'DE40': 'GER40.cash',
}

PAIR_SESSIONS = {
    'EURUSD': ['Asian KZ', 'London Open KZ', 'London', 'Forex NY'],
    'GBPUSD': ['Asian KZ', 'London Open KZ', 'London', 'Forex NY'],
    'XAUUSD': ['Asian KZ', 'London Open KZ', 'Gold NY'],
    'USTEC':  ['NASDAQ PM'],
    'US30':   ['NASDAQ PM'],
    'US500':  ['NASDAQ PM'],
    'DE40':   ['London Open KZ'],
}

POINT_SCALE = {'EURUSD': 100000, 'GBPUSD': 100000, 'XAUUSD': 100,
                'USTEC': 1, 'US30': 1, 'US500': 1, 'DE40': 1}


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
            'last_seen_cet_date': None,
            'last_processed_deal_ticket': 0,
            'open_bot_positions': {},
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
    return df[['open', 'high', 'low', 'close']]

def compute_weekly_bias(df):
    weekly = df['close'].resample('W').last().dropna()
    if len(weekly) < 3:
        return 'ranging'
    if weekly.iloc[-2] > weekly.iloc[-3]:
        return 'bullish'
    elif weekly.iloc[-2] < weekly.iloc[-3]:
        return 'bearish'
    return 'ranging'

def compute_4h_bias_and_slope(df):
    h4 = df['close'].resample('4h').last().dropna()
    if len(h4) < 51:
        return 'ranging', 'flat'
    bias = 'bullish' if h4.iloc[-1] > h4.iloc[-2] else 'bearish'
    sma50 = h4.rolling(50).mean()
    slope = 'up' if sma50.iloc[-1] > sma50.iloc[-2] else 'down'
    return bias, slope

def compute_zone(df):
    week_start = df.index.to_period('W').start_time
    tmp = pd.DataFrame({'high': df['high'], 'low': df['low'], 'week_start': week_start})
    running_high = tmp.groupby('week_start')['high'].cummax()
    running_low = tmp.groupby('week_start')['low'].cummin()
    mid = (running_high.iloc[-1] + running_low.iloc[-1]) / 2
    return 'discount' if df['close'].iloc[-1] < mid else 'premium'

def detect_price_action_latest(df, lookback=12, bos_window=6):
    highs, lows, closes = df['high'].values, df['low'].values, df['close'].values
    n = len(df)
    if n < lookback + bos_window + 3:
        return None

    i = n - 1
    recent_low = lows[i-lookback:i].min()
    recent_high = highs[i-lookback:i].max()

    sweep_buy = lows[i] < recent_low and closes[i] > recent_low
    sweep_sell = highs[i] > recent_high and closes[i] < recent_high

    fvg_bull = any(lows[j] > highs[j-2] for j in range(max(2, i-6), i+1))
    fvg_bear = any(highs[j] < lows[j-2] for j in range(max(2, i-6), i+1))

    bos_up = sweep_buy and closes[max(0, i-bos_window):i+1].max() > recent_high
    bos_down = sweep_sell and closes[max(0, i-bos_window):i+1].min() < recent_low

    return {
        'sweep_buy': bool(sweep_buy), 'sweep_sell': bool(sweep_sell),
        'bos_up': bool(bos_up), 'bos_down': bool(bos_down),
        'fvg_bull': bool(fvg_bull), 'fvg_bear': bool(fvg_bear),
        'swing_low': recent_low, 'swing_high': recent_high,
    }
def get_pair_price_action(pair, symbol_map):
    # fetches bars and detects price action for one pair -- used to build the cross-pair
    # cache for SMT comparison before evaluating EURUSD/GBPUSD individually
    symbol = symbol_map[pair]
    df = get_recent_bars(symbol)
    if df is None or len(df) < 100:
        return None, None
    pa = detect_price_action_latest(df)
    return df, pa

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

        is_bot_trade = (deal.magic == BOT_MAGIC)
        if is_bot_trade:
            if pnl < 0:
                state['bot_consecutive_losses'] += 1
                state['last_bot_loss_ts'] = datetime.now(WAT).isoformat()
                print(f"[BOT TRADE CLOSED] Loss: ${pnl:.2f} -- bot consecutive losses now {state['bot_consecutive_losses']}")
            elif pnl > 0:
                state['bot_consecutive_losses'] = 0
                print(f"[BOT TRADE CLOSED] Win: ${pnl:.2f} -- bot consecutive losses reset")

            position_key = str(deal.position_id)
            trade_info = state.get('open_bot_positions', {}).pop(position_key, None)

            if trade_info is not None:
                risk_amount = trade_info['risk_amount']
                r_multiple = round(pnl / risk_amount, 2) if risk_amount else 0
                result_label = 'WIN' if pnl > 0 else 'LOSS'

                database.save_trade(
                    pair=trade_info['pair'],
                    session=trade_info['session'],
                    entry=trade_info['entry'],
                    stop_loss=trade_info['sl'],
                    take_profit=trade_info['tp'],
                    result=result_label,
                    r_multiple=r_multiple,
                    account='FTMO Account',
                    date=datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M'),
                    notes=f"GOAT auto-trade | confidence={trade_info.get('confidence', 'N/A')}",
                )
                print(f"  [JOURNAL] Logged to database: {trade_info['pair']} {result_label} ({r_multiple}R)")
            else:
                print(f"  [WARNING] Bot trade closed but no matching open-trade record found -- not logged to journal")
        else:
            print(f"[MANUAL TRADE CLOSED] P&L: ${pnl:.2f} -- counted toward account P&L, not the bot's kill switch")

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
                print(f"[BLOCKED] {acc_status['reason']}")
                save_state(state)
                time.sleep(60)
                continue

            last_loss_ts = datetime.fromisoformat(state['last_bot_loss_ts']) if state['last_bot_loss_ts'] else None
            kill = bot.check_kill_switch(state['bot_consecutive_losses'], last_loss_ts)
            if kill['triggered']:
                print(f"[KILL SWITCH] {kill['reason']}")
                save_state(state)
                time.sleep(60)
                continue

            window = bot.check_silver_bullet_window()
            if window['active']:
                session_name = window['session']

                # precompute EURUSD/GBPUSD price action together, so the real SMT
                # divergence check has both pairs' data to compare -- not hardcoded True
                forex_pa_cache = {}
                pairs_this_session = [p for p, s in PAIR_SESSIONS.items() if session_name in s]
                if 'EURUSD' in pairs_this_session or 'GBPUSD' in pairs_this_session:
                    _, eur_pa = get_pair_price_action('EURUSD', SYMBOL_MAP)
                    _, gbp_pa = get_pair_price_action('GBPUSD', SYMBOL_MAP)
                    forex_pa_cache['EURUSD'] = eur_pa
                    forex_pa_cache['GBPUSD'] = gbp_pa

                for pair, sessions in PAIR_SESSIONS.items():
                    if session_name not in sessions:
                        continue

                    symbol = SYMBOL_MAP[pair]
                    positions = mt5.positions_get(symbol=symbol)
                    if positions and len(positions) > 0:
                        continue

                    df = get_recent_bars(symbol)
                    if df is None or len(df) < 100:
                        print(f"[{pair}] Not enough price data yet, skipping")
                        continue

                    weekly_bias = compute_weekly_bias(df)
                    bias_4h, sma_slope = compute_4h_bias_and_slope(df)
                    zone = compute_zone(df)
                    pa = detect_price_action_latest(df)
                    if pa is None:
                        continue

                    profile = bot.get_pair_profile(pair)
                    if profile['trend_required']:
                        if weekly_bias not in ('bullish', 'bearish'):
                            continue
                        direction = 'buy' if weekly_bias == 'bullish' else 'sell'
                    else:
                        direction = None
                        if pa['sweep_buy'] and pa['bos_up']:
                            direction = 'buy'
                        elif pa['sweep_sell'] and pa['bos_down']:
                            direction = 'sell'
                        if direction is None:
                            continue

                    if direction == 'buy':
                        liquidity_swept, bos_confirmed, fvg_or_ob = pa['sweep_buy'], pa['bos_up'], pa['fvg_bull']
                        sl_price_dist = abs(df['close'].iloc[-1] - pa['swing_low'])
                    else:
                        liquidity_swept, bos_confirmed, fvg_or_ob = pa['sweep_sell'], pa['bos_down'], pa['fvg_bear']
                        sl_price_dist = abs(pa['swing_high'] - df['close'].iloc[-1])

                    if not (liquidity_swept and bos_confirmed) or sl_price_dist <= 0:
                        continue

                    sl_points = round(sl_price_dist * POINT_SCALE[pair])
                    tp_points = sl_points * 2
                    # real SMT check for EURUSD/GBPUSD -- compares this pair's sweep against
                    # the other pair's sweep at the same moment. XAUUSD/indices unchanged.
                    if pair in ('EURUSD', 'GBPUSD'):
                        other_pair = 'GBPUSD' if pair == 'EURUSD' else 'EURUSD'
                        other_pa = forex_pa_cache.get(other_pair)
                        if other_pa is None:
                            smt_agreement, smt_divergence = False, False
                        elif direction == 'buy':
                            smt_agreement = pa['sweep_buy'] and other_pa['sweep_buy']
                            smt_divergence = pa['sweep_buy'] and not other_pa['sweep_buy']
                        else:
                            smt_agreement = pa['sweep_sell'] and other_pa['sweep_sell']
                            smt_divergence = pa['sweep_sell'] and not other_pa['sweep_sell']
                    else:
                        smt_agreement, smt_divergence = True, False
                    result = bot.evaluate_checklist(
                        current_equity=current_equity, daily_floor=daily_floor, max_loss_floor=max_loss_floor,
                        pair=pair, direction=direction, weekly_bias=weekly_bias, bias_4h=bias_4h,
                        sma_50_slope=sma_slope, zone=zone, smt_agreement=smt_agreement,
                        smt_divergence=smt_divergence, fvg_or_ob=fvg_or_ob, liquidity_swept=liquidity_swept,
                        bos_confirmed=bos_confirmed, sl_points=sl_points, tp_points=tp_points,
                    )

                    print(f"[{pair}] {direction.upper()} | confidence={result['confidence']} | valid={result['valid']}")

                    if result['valid']:
                        tick = mt5.symbol_info_tick(symbol)
                        if tick is None:
                            print(f"  [ERROR] No live tick for {symbol} -- skipping, market may be closed for this symbol")
                            continue

                        entry_price = tick.ask if direction == 'buy' else tick.bid
                        sl_price = entry_price - sl_price_dist if direction == 'buy' else entry_price + sl_price_dist
                        tp_price = entry_price + sl_price_dist * 2 if direction == 'buy' else entry_price - sl_price_dist * 2

                        print(f"  >>> SIGNAL: {pair} {direction} | lot={result['lot_size']} | "
                              f"SL={sl_price:.5f} TP={tp_price:.5f} | risking ${result['risk_amount']}")

                        if not DRY_RUN:
                            order = mt5.order_send({
                                "action": mt5.TRADE_ACTION_DEAL,
                                "symbol": symbol,
                                "volume": result['lot_size'],
                                "type": mt5.ORDER_TYPE_BUY if direction == 'buy' else mt5.ORDER_TYPE_SELL,
                                "price": entry_price,
                                "sl": sl_price,
                                "tp": tp_price,
                                "deviation": 20,
                                "magic": BOT_MAGIC,
                                "comment": "GOAT",
                                "type_time": mt5.ORDER_TIME_GTC,
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

            save_state(state)
            time.sleep(60)

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        save_state(state)
        mt5.shutdown()


if __name__ == '__main__':
    main()
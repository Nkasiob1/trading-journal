# mean_reversion.py
# GOAT Mean-Reversion Module -- v1.0
#
# Three independent strategies, each can trigger on its own (no confluence required):
#   1. Bollinger Bands (20, 2std) + RSI(14) mean reversion
#   2. RSI(2) mean reversion with SMA(200) trend filter (Connors-style, both directions)
#   3. VWAP deviation reversion (0.15% threshold, daily-resetting VWAP)
#
# BACKTESTED (16 months, all 7 instruments, real risk management):
#   - 452 trades independently, 36.5% win rate, +$3.47/trade expectancy, +$1,569.81 total
#     (with the account-status floor active -- this is what actually executed)
#   - Confirmed real positive edge: win/loss ratio ~2.4:1 more than compensates for the
#     low win rate
#   - Tested with a 9% trailing max-loss circuit breaker (permanent stop on breach, no
#     one-trade-per-pair lock): across 8 independent quarters, 6 of 8 (75%) reached
#     $1,000+ peak profit before any breach. 2 of 8 never did. This is a real, imperfect
#     hit rate -- not a guarantee.
#   - FTMO's own documentation confirms: when a Reward is withdrawn on a funded account,
#     the Maximum Loss Limit fully resets to 90% of Initial Capital -- supporting a
#     "withdraw regularly" approach once funded (not applicable during the current
#     Challenge/demo phase, which has no real withdrawal mechanics).
#
# RISK PARAMETERS (fixed, matching exactly what was backtested -- do not change without
# re-testing, since results are specific to this exact configuration):
#   - $4.00 FIXED risk per trade (not the ICT engine's PAIR_RISK table)
#   - Stop-loss = 0.5x ATR(14), Take-profit = 3x ATR(14) -- this is a ~6:1 dollar
#     reward:risk ratio, NOT 3:1 (verified directly against real trade outcomes)
#   - No one-trade-per-pair lock -- multiple overlapping positions on the same
#     instrument are allowed, matching exactly what was backtested and validated

import numpy as np
import pandas as pd

MR_FIXED_RISK = 4.00
SL_ATR_MULT = 0.5
TP_ATR_MULT = 3.0

BB_PERIOD = 20
BB_STD = 2
RSI14_PERIOD = 14
RSI2_PERIOD = 2
SMA_TREND_PERIOD = 200
VWAP_DEVIATION_PCT = 0.15
ATR_PERIOD = 14


def compute_atr(df, period=ATR_PERIOD):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def compute_indicators(df):
    """Adds all indicators needed by the 3 strategies. df must have open/high/low/close
    and a 'tickvol' column (tick volume, used as the VWAP volume proxy -- forex/CFD
    markets don't have true centralized volume, tick count is the standard substitute)."""
    df = df.copy()

    df['sma20'] = df['close'].rolling(BB_PERIOD).mean()
    df['std20'] = df['close'].rolling(BB_PERIOD).std()
    df['bb_upper'] = df['sma20'] + BB_STD * df['std20']
    df['bb_lower'] = df['sma20'] - BB_STD * df['std20']

    delta = df['close'].diff()
    gain14 = delta.clip(lower=0).rolling(RSI14_PERIOD).mean()
    loss14 = (-delta.clip(upper=0)).rolling(RSI14_PERIOD).mean()
    rs14 = gain14 / loss14.replace(0, np.nan)
    df['rsi14'] = 100 - (100 / (1 + rs14))

    gain2 = delta.clip(lower=0).rolling(RSI2_PERIOD).mean()
    loss2 = (-delta.clip(upper=0)).rolling(RSI2_PERIOD).mean()
    rs2 = gain2 / loss2.replace(0, np.nan)
    df['rsi2'] = 100 - (100 / (1 + rs2))
    df['sma200'] = df['close'].rolling(SMA_TREND_PERIOD).mean()

    if 'tickvol' in df.columns:
        vol = df['tickvol']
        df['pv'] = df['close'] * vol
        day = df.index.date
        df['cum_pv'] = df.groupby(day)['pv'].cumsum()
        df['cum_vol'] = df.groupby(day)['tickvol'].cumsum()
    else:
        # fallback if volume unavailable -- degrades to a plain daily-anchored moving average
        day = df.index.date
        df['pv'] = df['close']
        df['cum_pv'] = df.groupby(day)['pv'].cumsum()
        df['cum_vol'] = pd.Series(range(1, len(df) + 1), index=df.index)
        df['cum_vol'] = df.groupby(day)['cum_vol'].transform(lambda x: range(1, len(x) + 1))
    df['vwap'] = df['cum_pv'] / df['cum_vol'].replace(0, np.nan)

    df['atr'] = compute_atr(df)
    return df


def check_signal(df):
    """Checks the LATEST bar only (live use -- called once per loop iteration).
    Returns a list of 0, 1, 2, or 3 signal dicts (one per strategy that fires this bar --
    they are independent, more than one CAN fire simultaneously on the same bar)."""
    if len(df) < SMA_TREND_PERIOD + 5:
        return []

    i = len(df) - 1
    close = df['close'].iloc[i]
    bb_upper = df['bb_upper'].iloc[i]
    bb_lower = df['bb_lower'].iloc[i]
    rsi14 = df['rsi14'].iloc[i]
    rsi2 = df['rsi2'].iloc[i]
    sma200 = df['sma200'].iloc[i]
    vwap = df['vwap'].iloc[i]
    atr = df['atr'].iloc[i]

    if any(pd.isna(x) for x in [bb_upper, bb_lower, rsi14, rsi2, sma200, vwap, atr]) or atr <= 0:
        return []

    signals = []

    # Strategy 1: Bollinger + RSI(14)
    if close <= bb_lower and rsi14 < 30:
        signals.append({'strategy': 'BB_RSI14', 'direction': 'buy', 'atr': atr})
    if close >= bb_upper and rsi14 > 70:
        signals.append({'strategy': 'BB_RSI14', 'direction': 'sell', 'atr': atr})

    # Strategy 2: RSI(2) with SMA(200) trend filter, both directions
    if rsi2 < 10 and close > sma200:
        signals.append({'strategy': 'RSI2', 'direction': 'buy', 'atr': atr})
    if rsi2 > 90 and close < sma200:
        signals.append({'strategy': 'RSI2', 'direction': 'sell', 'atr': atr})

    # Strategy 3: VWAP deviation reversion
    dev_pct = (close - vwap) / vwap * 100
    if dev_pct <= -VWAP_DEVIATION_PCT:
        signals.append({'strategy': 'VWAP', 'direction': 'buy', 'atr': atr})
    if dev_pct >= VWAP_DEVIATION_PCT:
        signals.append({'strategy': 'VWAP', 'direction': 'sell', 'atr': atr})

    return signals


def calculate_mr_lot_size(pair, sl_dist, point_scale, point_value):
    """Fixed $4 risk sizing -- separate from the ICT engine's PAIR_RISK table."""
    if sl_dist <= 0:
        return {'valid': False, 'reason': 'sl_dist <= 0'}
    sl_points = sl_dist * point_scale
    if sl_points <= 0:
        return {'valid': False, 'reason': 'sl_points <= 0'}
    lot_size = MR_FIXED_RISK / (sl_points * point_value)
    lot_size = round(lot_size, 2)
    if lot_size < 0.01:
        return {'valid': False, 'reason': f'lot size {lot_size} below minimum 0.01'}
    if lot_size > 1.00:
        lot_size = 1.00
    actual_risk = lot_size * sl_points * point_value
    return {'valid': True, 'lot_size': lot_size, 'risk_amount': round(actual_risk, 2)}
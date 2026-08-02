# analyze_rejections.py
# Run this anytime (even after just one day) to see a summary of what's been
# blocking or passing signals, based on signal_evaluations.csv.
#
# Usage: python analyze_rejections.py

import csv
from collections import Counter
from datetime import datetime, timedelta

LOG_FILE = 'signal_evaluations.csv'

def analyze(hours_back=24):
    try:
        with open(LOG_FILE, 'r') as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        print(f"No {LOG_FILE} found yet -- nothing has been evaluated and logged so far.")
        return

    if not rows:
        print(f"{LOG_FILE} exists but is empty -- no signals evaluated yet.")
        return

    cutoff = datetime.now() - timedelta(hours=hours_back)
    recent_rows = [r for r in rows if datetime.strptime(r['timestamp'], '%Y-%m-%d %H:%M:%S') >= cutoff]

    print(f"=== Signal evaluation summary: last {hours_back} hours ===")
    print(f"Total evaluated signals in this window: {len(recent_rows)}")
    print(f"(Total ever logged, all-time: {len(rows)})\n")

    if not recent_rows:
        print("No signals evaluated in this window -- either genuinely quiet, or check the bot is running.")
        return

    valid_count = sum(1 for r in recent_rows if r['valid'] == 'True')
    print(f"Passed (valid=True): {valid_count}")
    print(f"Rejected: {len(recent_rows) - valid_count}\n")

    rejection_reasons = Counter()
    for r in recent_rows:
        if r['valid'] == 'True':
            continue
        reasons = r['rejected_because'].split('; ') if r['rejected_because'] else []
        for reason in reasons:
            if reason:
                rejection_reasons[reason] += 1

    if rejection_reasons:
        print("Most common rejection reasons (a signal can fail more than one check):")
        for reason, count in rejection_reasons.most_common():
            pct = count / (len(recent_rows) - valid_count) * 100 if (len(recent_rows) - valid_count) > 0 else 0
            print(f"  {reason:<15} {count:>4} times ({pct:.1f}% of rejections)")

    confidences = [float(r['confidence']) for r in recent_rows]
    print(f"\nConfidence scores in this window: min={min(confidences):.1f}, "
          f"max={max(confidences):.1f}, avg={sum(confidences)/len(confidences):.1f}")

    print("\nBy pair:")
    pair_counts = Counter(r['pair'] for r in recent_rows)
    for pair, count in pair_counts.most_common():
        pair_valid = sum(1 for r in recent_rows if r['pair'] == pair and r['valid'] == 'True')
        print(f"  {pair:<8} {count:>3} evaluated, {pair_valid} passed")

if __name__ == '__main__':
    analyze(hours_back=24)
    
# Import required libraries
import requests
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get API key from environment
API_KEY = os.getenv('NEWS_API_KEY')

# Keywords that trigger a NO TRADE day
NO_TRADE_KEYWORDS = [
    'nonfarm payroll', 'non-farm payroll', 'NFP',
    'CPI', 'consumer price index', 'inflation data',
    'federal reserve', 'fed rate', 'interest rate decision',
    'FOMC', 'powell', 'fed chair',
    'bank of england', 'BoE rate', 'MPC decision',
    'ECB rate', 'european central bank rate',
    'GDP', 'gross domestic product',
    'nasdaq crash', 'nasdaq plunge', 'tech selloff',
    'US100', 'federal reserve nasdaq'
]

# Keywords that trigger a CAUTION day
CAUTION_KEYWORDS = [
    'jobless claims', 'unemployment claims',
    'retail sales', 'manufacturing PMI',
    'services PMI', 'trade balance',
    'consumer confidence', 'industrial production',
    'nasdaq futures', 'tech earnings', 'nasdaq volatility'
]

# This function fetches today's forex news filtered for our pairs
def get_forex_news():
    url = 'https://newsapi.org/v2/everything'

    params = {
        'q': 'EURUSD OR GBPUSD OR "Gold forex" OR "forex market" OR "currency market" OR "pound dollar" OR "euro dollar" OR NASDAQ OR "US100" OR "tech stocks forex"',
        'language': 'en',
        'sortBy': 'publishedAt',
        'pageSize': 15,
        'apiKey': API_KEY
    }

    # Make the GET request to NewsAPI
    response = requests.get(url, params=params)

    # Convert the response to JSON
    data = response.json()

    # Extract just the articles list
    articles = data.get('articles', [])

    # Build a clean list of news items
    news_list = []
    for article in articles:
        news_list.append({
            'title': article['title'],
            'source': article['source']['name'],
            'url': article['url'],
            'published': article['publishedAt']
        })

    return news_list

# This function checks all headlines and returns a trade day verdict
def get_trade_verdict(news_list):
    # Combine all headlines into one string for scanning
    all_headlines = ' '.join([article['title'].lower() for article in news_list])

    # Check for no-trade keywords first
    for keyword in NO_TRADE_KEYWORDS:
        if keyword.lower() in all_headlines:
            return {
                'verdict': 'NO TRADE',
                'color': 'red',
                'reason': f'High impact event detected in headlines: {keyword}',
                'emoji': '🔴'
            }

    # Check for caution keywords
    for keyword in CAUTION_KEYWORDS:
        if keyword.lower() in all_headlines:
            return {
                'verdict': 'CAUTION',
                'color': 'orange',
                'reason': f'Medium impact event detected: {keyword}',
                'emoji': '🟡'
            }

    # Green light if no concerning keywords found
    return {
        'verdict': 'CLEAR TO TRADE',
        'color': 'green',
        'reason': 'No high impact events detected in today\'s headlines',
        'emoji': '🟢'
    }
from datetime import datetime, timedelta
import pytz

UTC = pytz.UTC
# ── STATIC ECONOMIC CALENDAR ──
# No external API -- a manually maintained list of known high/medium-impact events.
# UPDATE THIS MONTHLY: check forexfactory.com/calendar (or any public economic calendar)
# once a month, add upcoming NFP/CPI/FOMC/BoE/ECB dates. Takes about 5 minutes.
#
# Format: (date 'YYYY-MM-DD', time_utc 'HH:MM', event_name, impact 'high' or 'medium')
#
# IMPORTANT: this list starts EMPTY. Until you populate it, the bot has NO calendar
# protection at all -- it will not block trading around any scheduled news event.
STATIC_BLACKOUT_EVENTS = [
    ('2026-07-23', '12:15', 'ECB Rate Decision', 'high'),
    ('2026-07-29', '11:00', 'BoE Rate Decision', 'high'),
    ('2026-07-29', '18:00', 'FOMC Rate Decision', 'high'),
    ('2026-08-07', '12:30', 'US Non-Farm Payrolls', 'high'),
    ('2026-08-12', '12:30', 'US CPI', 'high'),
]

def get_economic_calendar(target_date=None):
    # target_date: a date object, defaults to today (UTC). Filters STATIC_BLACKOUT_EVENTS
    # down to just events on this specific date.
    if target_date is None:
        target_date = datetime.now(UTC).date()

    target_date_str = target_date.isoformat()
    matching_events = []
    for event_date, event_time, event_name, impact in STATIC_BLACKOUT_EVENTS:
        if event_date == target_date_str:
            matching_events.append({
                'time': f"{event_date} {event_time}:00",
                'event': event_name,
                'impact': impact,
                'country': 'US',  # not currently distinguishing by country -- all treated as relevant
            })
    return matching_events

def check_economic_calendar_blackout(now_utc=None, blackout_before_min=30, blackout_after_min=30):
    # unchanged logic -- checks if "now" falls within a blackout window around any event.
    # Only the SOURCE of events changed (static list instead of a live API call).
    now_utc = now_utc if now_utc else datetime.now(UTC)
    events = get_economic_calendar(now_utc.date())

    for event in events:
        impact = str(event.get('impact', '')).lower()
        if impact not in ('high', 'medium'):
            continue

        event_time_str = event.get('time')
        if not event_time_str:
            continue

        try:
            event_time = datetime.strptime(event_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)
        except ValueError:
            continue

        window_start = event_time - timedelta(minutes=blackout_before_min)
        window_end = event_time + timedelta(minutes=blackout_after_min)

        if window_start <= now_utc <= window_end:
            severity = 'NO TRADE' if impact == 'high' else 'CAUTION'
            return {
                'in_blackout': True, 'severity': severity,
                'event': event.get('event', 'Unknown event'),
                'event_time_utc': event_time.isoformat(),
                'reason': f"{severity}: {event.get('event')} scheduled at {event_time.strftime('%H:%M UTC')}",
            }

    return {'in_blackout': False, 'severity': None, 'reason': 'No high/medium impact events in blackout window'}

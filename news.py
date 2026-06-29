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
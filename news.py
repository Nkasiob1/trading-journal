# Import libraries
import requests
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get API key from environment — never hardcoded
API_KEY = os.getenv('NEWS_API_KEY')

# This function fetches today's financial news for our pairs
def get_forex_news():
    # The NewsAPI endpoint for everything
    url = 'https://newsapi.org/v2/everything'
    
    # Parameters for the request
    params = {
        'q': 'EURUSD OR GBPUSD OR Gold forex',
        'language': 'en',
        'sortBy': 'publishedAt',
        'pageSize': 10,
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
    
    # Return the news list
    return news_list
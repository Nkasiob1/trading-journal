# Import required libraries
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
from news import get_forex_news, get_trade_verdict

# Load environment variables
load_dotenv()

# This function builds and sends the morning briefing email
def send_morning_briefing():
    # Get credentials from environment
    EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')
    BREVO_SMTP_SERVER = os.getenv('BREVO_SMTP_SERVER')
    BREVO_PORT = int(os.getenv('BREVO_PORT'))
    BREVO_LOGIN = os.getenv('BREVO_LOGIN')
    BREVO_PASSWORD = os.getenv('BREVO_PASSWORD')

    # Get today's news and verdict
    articles = get_forex_news()
    verdict = get_trade_verdict(articles)

    # Build the email subject
    subject = f"GOAT Morning Briefing — {verdict['emoji']} {verdict['verdict']}"

    # Build the email body in HTML
    body = f"""
    <html>
    <body style="background-color:#1c1208; color:#f0ead6; font-family:Arial, sans-serif; padding:20px;">
        
        <h1 style="color:#7a9e7e;">GOAT Morning Briefing</h1>
        
        <h2>Today's Trade Verdict</h2>
        <div style="padding:15px; border-radius:8px; background-color:#2a1f10; border:2px solid #7a9e7e; margin-bottom:20px;">
            <h3>{verdict['emoji']} {verdict['verdict']}</h3>
            <p>{verdict['reason']}</p>
        </div>

        <h2 style="color:#7a9e7e;">Today's Forex & Market News</h2>
    """

    # Add each article to the email
    for article in articles:
        body += f"""
        <div style="padding:12px; background-color:#2a1f10; border-radius:8px; margin-bottom:10px; border:1px solid #3d2b15;">
            <a href="{article['url']}" style="color:#a8c5a0; text-decoration:none;">
                <strong>{article['title']}</strong>
            </a>
            <p style="color:#b5a48a; font-size:0.85rem;">{article['source']} — {article['published']}</p>
        </div>
        """

    body += """
    </body>
    </html>
    """

    # Create the email message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = EMAIL_ADDRESS

    # Attach the HTML body
    msg.attach(MIMEText(body, 'html'))

    # Send the email using Brevo's SMTP server
    try:
        with smtplib.SMTP(BREVO_SMTP_SERVER, BREVO_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(BREVO_LOGIN, BREVO_PASSWORD)
            server.sendmail(BREVO_LOGIN, EMAIL_ADDRESS, msg.as_string())
            print("Morning briefing sent successfully")
    except Exception as e:
        print(f"Failed to send email: {e}")

# Run when this file is executed directly
if __name__ == '__main__':
    send_morning_briefing()
# Import required libraries
import schedule
import time
from emailer import send_morning_briefing

# Schedule the morning briefing at 7:00 AM every day
schedule.every().day.at("06:00").do(send_morning_briefing)
# 06:00 UTC = 07:00 WAT (West Africa Time is UTC+1)

print("GOAT Scheduler running — morning briefing scheduled for 7:00 AM WAT")

# Keep the scheduler running
while True:
    schedule.run_pending()
    time.sleep(60)
# Use a lightweight Python 3.11 base image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install all dependencies from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and Chromium
RUN pip install playwright
RUN playwright install --with-deps chromium

# Copy all project files into the container
COPY . .

# Expose port 5000
EXPOSE 5000

# Run the Flask app
CMD ["python", "app.py"]
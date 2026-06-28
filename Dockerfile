# Use a lightweight Python 3.11 base image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy all project files into the container
COPY . .

# Install all Python dependencies
RUN pip install flask requests python-dotenv pytest

# Expose port 5000 so the browser can reach the Flask app
EXPOSE 5000

# Run the Flask app when the container starts
CMD ["python", "app.py"]
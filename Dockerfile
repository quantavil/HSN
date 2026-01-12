FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Set working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install dependencies and browsers
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium

# Copy application code
COPY . .

# Expose the dashboard port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "dashboard.server:app", "--host", "0.0.0.0", "--port", "8000"]

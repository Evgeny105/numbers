# Use the official Python 3.11 image as the base
FROM python:3.11-slim

# Install necessary dependencies
RUN apt-get update && apt-get install -y \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy all files to the working directory in the container
COPY . /app

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Specify the command to run the bot
CMD ["python", "bot.py"]
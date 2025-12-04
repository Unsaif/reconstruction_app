# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for Graphviz
RUN apt-get update && apt-get install -y \
    graphviz \
    && rm -rf /var/lib/apt/lists/*

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 8502 available to the world outside this container
EXPOSE 8502

# Define environment variable
ENV PYTHONUNBUFFERED=1

# Run app.py when the container launches
CMD ["streamlit", "run", "app.py", "--server.port=8502", "--server.address=0.0.0.0"]

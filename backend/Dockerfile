
# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Set the working directory to /app
WORKDIR /app

# Install system dependencies
# We need curl/gnupg for installing cloud tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    ca-certificates \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# 1. Install Kubectl
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/

# 2. Install AWS CLI (v2)
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && \
    unzip awscliv2.zip && \
    ./aws/install && \
    rm -rf aws awscliv2.zip

# 3. Install Azure CLI
RUN curl -sL https://aka.ms/InstallAzureCLIDeb | bash

# Copy requirements file (create one if it doesn't exist, we'll generate it next)
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . .

# Inject licensing constants at build time — values land in source, not in ENV
ARG LICENSE_SERVER_URL=""
ARG ACTIVATION_ENABLED="false"
RUN sed -i "s|__LICENSE_SERVER_URL__|${LICENSE_SERVER_URL}|g" /app/app/core/license_constants.py && \
    sed -i "s|__ACTIVATION_ENABLED__|${ACTIVATION_ENABLED}|g" /app/app/core/license_constants.py

# Remove any SQLite database files that may have slipped through the build context.
# The database must be provided via a persistent volume at runtime, not baked into the image.
RUN find /app -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" | xargs rm -f

# Expose port 8000
EXPOSE 8000

# Define environment variable
ENV MODULE_NAME="app.main"
ENV VARIABLE_NAME="app"
ENV PORT="8000"

# Run app.main:app when the container launches
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

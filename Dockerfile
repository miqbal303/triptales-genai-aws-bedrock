# Use official Python 3.11 base image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy the current directory contents into the container
COPY . .

# Install OS packages and AWS CLI
RUN apt-get update && \
    apt-get install -y awscli && \
    apt-get clean

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port App Runner expects
EXPOSE 8080

# Run Streamlit app on port 8080
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0"]

# Use the smaller Python image for production
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Install system dependencies: OpenCV, Tesseract, and GL (needed for cv2)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    tesseract-ocr \
    tesseract-ocr-eng && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy your project files
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set the default command
CMD ["python", "main.py"]

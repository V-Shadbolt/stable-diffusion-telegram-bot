FROM python:3.10-slim

# Install pip requirements
COPY requirements.txt .
COPY bot.py .
RUN python -m pip install -r requirements.txt

CMD ["python", "bot.py"]

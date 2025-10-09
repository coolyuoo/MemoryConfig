FROM python:3.11-slim

WORKDIR /app

COPY req.txt ./req.txt

RUN pip install --no-cache-dir -r req.txt

COPY app.py ./app.py

EXPOSE 8000

CMD ["python", "app.py"]

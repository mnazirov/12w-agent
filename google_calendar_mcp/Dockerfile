FROM python:3.12-slim

WORKDIR /app

COPY google_calendar_mcp/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY google_calendar_mcp/ /app/

EXPOSE 8002

CMD ["python", "run.py"]

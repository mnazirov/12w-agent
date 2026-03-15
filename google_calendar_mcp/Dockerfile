FROM python:3.12-slim

WORKDIR /app

COPY google_calendar_mcp/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# TODO: Replace mock server with real package (example):
# RUN pip install --no-cache-dir google-calendar-mcp
# or RUN npm install -g @your-org/google-calendar-mcp

COPY google_calendar_mcp/ /app/

EXPOSE 8002

CMD ["python", "run.py"]

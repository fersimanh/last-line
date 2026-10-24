# Last Line, cache-only: the app serves the saved match and the saved AI texts.
# It never calls the agents (no key, no Azure login needed).
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    LAST_LINE_LIVE_AGENTS=0

COPY requirements-app.txt .
RUN pip install -r requirements-app.txt

# Only what the app reads: its code, the stylesheet settings, the match, the tracking and the cache.
COPY app.py insights.py inspector.py perception.py vision.py tracking.py matchclock.py \
     replay.py scoring.py selection.py theme.py ./
COPY .streamlit/config.toml .streamlit/config.toml
COPY match_events.json tracking.npz insight_cache.json ./

EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8501/_stcore/health')" || exit 1
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]

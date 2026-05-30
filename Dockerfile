FROM python:3.12-slim
WORKDIR /app

# default-jre-headless: powerplantmatching uses Duke (Java) for fuzzy matching
# build-essential + libgdal: earth-osm pyrosm parser needs native deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    build-essential \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
COPY utils/ utils/
COPY models/ models/
COPY sql/ sql/
COPY scripts/ scripts/
COPY migrations/ migrations/
COPY pipeline.py ./
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

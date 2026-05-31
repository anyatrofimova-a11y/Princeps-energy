FROM python:3.12-slim
WORKDIR /app

# Build deps for trafilatura + lxml + rapidfuzz wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Reuse the main backend requirements so agents have access to utils.*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code agents depend on
COPY app/ app/
COPY utils/ utils/
COPY migrations/ migrations/
COPY agents/ agents/

# AGENT_MODULE is set per Railway service (graph | connector | regwatch |
# grid | screen | contracts | market | replay | council). The CMD invokes
# `python -m agents.$AGENT_MODULE`.
ENV PYTHONUNBUFFERED=1
ENV AGENT_MODULE=graph
EXPOSE 8080
CMD ["sh", "-c", "python -m agents.$AGENT_MODULE"]

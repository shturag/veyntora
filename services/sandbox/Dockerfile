# Code sandbox for the chat's code interpreter (ADR 0030).
# Build from the repository root: docker build -f services/sandbox/Dockerfile .
FROM python:3.12.16-slim-trixie

COPY services/sandbox/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-compile -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && python -c "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot"
COPY services/sandbox/server.py /app/server.py

# Runs as nobody on a read-only file system; each run writes only to its folder in /tmp.
USER 65534:65534
WORKDIR /tmp
EXPOSE 8090
CMD ["python", "-I", "/app/server.py"]

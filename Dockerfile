FROM python:3.14.2-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ADA_PROFILE=cloud

WORKDIR /app

COPY requirements-web.txt /app/requirements-web.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
      -r /app/requirements-web.txt \
    && groupadd --system ada \
    && useradd --system --gid ada --home-dir /app ada

COPY ada /app/ada
COPY web /app/web
COPY assets/persona.md /app/assets/persona.md
COPY assets/skills /app/assets/skills
COPY corpus /app/corpus
COPY ingest /app/ingest

USER ada
EXPOSE 8765
CMD ["python", "-m", "ada.web"]

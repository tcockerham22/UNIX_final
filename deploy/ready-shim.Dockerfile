FROM python:3.14.2-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY deploy/ready_shim.py /app/ready_shim.py
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin shim
USER shim
EXPOSE 8080
CMD ["python", "/app/ready_shim.py"]

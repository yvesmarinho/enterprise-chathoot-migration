# ============================================================
# Dockerfile — enterprise-chathoot-migration
# Executa o pipeline de migração perto do banco (wfdb01 → wfdb02)
# ============================================================
FROM python:3.12-slim

# Evita bytecode e bufferização desnecessários em logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependências de sistema mínimas para psycopg2-binary
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copia apenas o manifesto de dependências primeiro (layer cache)
COPY docker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código-fonte (sem .secrets — montado em runtime)
COPY app/     /app/app/
COPY src/     /app/src/
COPY scripts/ /app/scripts/

# Ponto de entrada padrão: migration entrypoint
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]

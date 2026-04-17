FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The [all] extra pulls every format converter (pdf, docx, pptx, xlsx, audio,
# youtube, etc.). Pin markitdown to a known-good minor to keep installs reproducible.
RUN pip install --no-cache-dir \
    'markitdown[all]==0.1.3' \
    'fastapi==0.115.6' \
    'uvicorn[standard]==0.34.0' \
    'python-multipart==0.0.20'

COPY server.py /app/server.py

EXPOSE 3000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "3000"]

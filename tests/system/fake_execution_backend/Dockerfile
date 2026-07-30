# Test-only fake execution backend (Slice 2B Batch B packet §5). NOT the real
# Judge0 VM. Runs the product's canonical coding harness on a REAL local
# toolchain (python/javac+java/g++) so Accepted/compile_error/test_mismatch are
# genuine, deterministic outcomes. Never packaged into production.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ default-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY tests/system/fake_execution_backend/server.py /app/server.py

ENV FAKE_EXEC_PORT=8110
EXPOSE 8110

# Sanity gate at build time: the three toolchains must be present, else the
# image must fail to build rather than silently passing as Judge0.
RUN python -c "import shutil,sys; [shutil.which(t) or sys.exit('missing '+t) for t in ('python','javac','java','g++')]"

CMD ["python", "server.py"]

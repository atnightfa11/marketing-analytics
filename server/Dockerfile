FROM python:3.12-slim AS builder
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install --upgrade pip && pip wheel --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY --from=builder /wheels /wheels
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache /wheels/*
RUN python - <<'PY'
from pathlib import Path

import prophet

stan_model_dir = Path(prophet.__file__).resolve().parent / "stan_model"
candidates = sorted(stan_model_dir.glob("cmdstan-*"))
if not candidates:
    raise SystemExit("No bundled CmdStan directory found in prophet package")

candidate = next((c for c in candidates if (c / "bin").exists()), None)
if candidate is None:
    raise SystemExit("No bundled CmdStan candidate with bin/ found")

makefile = candidate / "makefile"
if not makefile.exists():
    makefile.write_text("# generated during image build for cmdstanpy validation\n", encoding="utf-8")

print(f"Prepared bundled CmdStan at {candidate}")
PY
COPY . .
EXPOSE 8000
CMD ["sh", "-c", "if [ \"$VALID_PROCESS_TYPE\" = \"worker\" ]; then python -m app.worker; else uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}; fi"]

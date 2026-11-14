# Hugging Face Space (Docker SDK). AI-assisted: written with Claude (Anthropic) and reviewed by the team.
FROM python:3.10-slim

# Spaces run the container as user 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1 PORT=7860 HOST=0.0.0.0
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user app ./app
COPY --chown=user scripts ./scripts
COPY --chown=user data/geo ./data/geo

EXPOSE 7860
CMD ["bash", "scripts/start.sh"]

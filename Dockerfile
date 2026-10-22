FROM python:3.12-slim

# Deno runs Code Mode programs from coding agents in a sandbox.
COPY --from=denoland/deno:bin-2.9.8 /deno /usr/local/bin/deno

RUN useradd --create-home --uid 1000 masterapi
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY masterapi ./masterapi
RUN pip install --no-cache-dir .

# Containers have no OS keyring: pass the vault key with -e MASTERAPI_KEY=...
# (generate one with `masterapi keygen`) and keep the vault on a volume.
ENV MASTERAPI_HOME=/data
RUN mkdir /data && chown masterapi /data
VOLUME /data
USER masterapi

EXPOSE 8787
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health')"
CMD ["masterapi", "serve", "--host", "0.0.0.0", "--port", "8787"]

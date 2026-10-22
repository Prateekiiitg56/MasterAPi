#!/usr/bin/env sh
# MASTERAPI_TOKEN=<token> sh examples/curl.sh
BASE=http://127.0.0.1:8787
AUTH="Authorization: Bearer $MASTERAPI_TOKEN"

curl -s "$BASE/v1/models" -H "$AUTH"

curl -s "$BASE/v1/chat/completions" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"model": "gemini", "messages": [{"role": "user", "content": "Hi"}]}'

curl -s "$BASE/v1/embeddings" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"model": "openai", "input": "hello"}'

curl -s "$BASE/v1/images/generations" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"model": "openai", "prompt": "a red fox"}'

# Raw passthrough: OpenAI text-to-speech through the "openai" alias
curl -s "$BASE/proxy/openai/audio/speech" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o-mini-tts", "voice": "alloy", "input": "Hello"}' -o hello.mp3

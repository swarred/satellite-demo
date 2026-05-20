#!/bin/bash
# Pre-warm llama3.2:1b into Ollama's memory so the first classification
# request doesn't incur a cold-load penalty.

for i in $(seq 1 24); do
    curl -sf http://localhost:11434/api/tags &>/dev/null && break
    sleep 5
done

for i in $(seq 1 12); do
    CODE=$(curl -s -o /dev/null -w '%{http_code}' \
        http://localhost:11434/api/generate \
        -d '{"model":"llama3.2:1b","prompt":"hi","stream":false,"options":{"num_predict":1}}')
    [ "$CODE" = "200" ] && exit 0
    sleep 5
done

exit 1

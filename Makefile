.PHONY: dev test install deploy worker-dev clean

PORT ?= 8000

install:
	uv sync

dev:
	uv run uvicorn app.main:app --reload --port $(PORT)

test:
	uv run pytest

worker-dev:
	bun install
	bun run dev

deploy:
	bun run deploy

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +

# kill -9 $(lsof -t -i:8000 -sTCP:LISTEN)
# pgrep -f uvicorn; ss -tlnp 2>/dev/null | grep 8765 || echo "port clear"

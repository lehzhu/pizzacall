# voicedemo

Pizza order voice agent MVP.

## Run

```bash
uv sync
uv run uvicorn app.api:app --reload
uv run python -m app.cli --store +15125550199 --order-file examples/order.json
```


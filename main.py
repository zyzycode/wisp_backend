"""ASGI entry point: python main.py or uvicorn main:app."""

import uvicorn

from wisp_backend.application import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)

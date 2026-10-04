"""ASGI entry point:  uvicorn investigator.main:app  (or: python -m investigator.main)"""
import logging
import os

from .app import create_app

logging.basicConfig(level=os.environ.get("DOCINV_LOG", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))

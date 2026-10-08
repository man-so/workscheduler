import os

import uvicorn

from app.main import app


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("WORKSCHEDULER_HOST", "127.0.0.1"),
        port=int(os.getenv("WORKSCHEDULER_PORT", "8000")),
    )

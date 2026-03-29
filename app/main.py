from __future__ import annotations

import uvicorn

from app.config import get_settings
from app.server import create_app

app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()

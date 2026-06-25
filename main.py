"""Local launcher: `uv run python main.py` starts the dev API server.

In production the app is served by uvicorn inside the Docker container; this is
just a convenience entrypoint for running the backend on the host.
"""

import uvicorn


def main() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()

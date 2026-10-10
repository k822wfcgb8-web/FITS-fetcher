"""`fits-fetcher` command: start the local server and open the search page (REQ-09, REQ-28, S-36)."""
from __future__ import annotations

import argparse
import logging
import socket
import threading
import webbrowser

import uvicorn

from fits_fetcher import __version__
from fits_fetcher.config import Settings, log_path
from fits_fetcher.web.app import create_app

HOST = "127.0.0.1"  # localhost only: never reachable from the network (REQ-09)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def setup_logging() -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path), logging.StreamHandler()])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="fits-fetcher", description=__doc__)
    parser.add_argument("--port", type=int, default=0, help="port to use (default: pick a free one)")
    parser.add_argument("--no-browser", action="store_true", help="don't open the page in a browser")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    setup_logging()
    port = args.port or free_port()
    server: uvicorn.Server | None = None

    def quit_server() -> None:
        if server:
            server.should_exit = True

    app = create_app(Settings.load(), on_quit=quit_server)
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_level="warning"))
    url = f"http://{HOST}:{port}/"
    print(f"FITS-fetcher {__version__} running at {url}  (press Ctrl+C or use Quit on the page to stop)")
    print(f"Log file: {log_path()}")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    server.run()  # returns on Ctrl+C or Quit; uvicorn shuts down cleanly in both cases


if __name__ == "__main__":
    main()

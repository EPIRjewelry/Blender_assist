"""CLI entry: python -m desktop_agent"""

from __future__ import annotations

from desktop_agent.config import load_settings
from desktop_agent.http_server import run_server


def main() -> None:
    run_server(load_settings())


if __name__ == "__main__":
    main()

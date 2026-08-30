from __future__ import annotations

import sys

from .config import build_parser, load_config
from .mcp_server import run_mcp_server
from .server import StdioServer


def main() -> int:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    args = build_parser().parse_args()
    config = load_config(args)
    if args.ndjson:
        return StdioServer(config).run()
    run_mcp_server(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())

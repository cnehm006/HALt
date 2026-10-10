"""python -m halt.web starts the local console and its C++ simulator."""

import argparse

import uvicorn

from halt.web.app import create_app

parser = argparse.ArgumentParser(description="HALt local engineering console")
parser.add_argument("--port", type=int, default=8000)
args = parser.parse_args()
if not 1 <= args.port <= 65535:
    parser.error("port must be in [1,65535]")
uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="info", access_log=False)

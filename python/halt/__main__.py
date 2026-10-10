"""Read a running simulator: PYTHONPATH=python python -m halt."""

import argparse

from google.protobuf.json_format import MessageToJson

from halt.client import DeviceClient

parser = argparse.ArgumentParser(description="Inspect the HALt simulated device over gRPC")
parser.add_argument("--address", default="127.0.0.1:50051")
args = parser.parse_args()
client = DeviceClient(args.address)
try:
    print(MessageToJson(client.call("GetTelemetry")))
finally:
    client.close()

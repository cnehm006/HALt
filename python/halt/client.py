"""Small typed-client convenience layer with explicit RPC deadlines."""

import math
import time

import grpc

from halt.generated import halt_pb2 as pb
from halt.generated import halt_pb2_grpc as bindings


class DeviceClient:
    def __init__(self, address: str, timeout: float = 1.0):
        self.channel = grpc.insecure_channel(address)
        self.rpc = bindings.DeviceControlStub(self.channel)
        self.timeout = timeout

    def close(self):
        self.channel.close()

    def call(self, name, request=None, *, timeout=None):
        return getattr(self.rpc, name)(
            pb.Empty() if request is None else request,
            timeout=self.timeout if timeout is None else timeout,
        )

    def wait_state(self, state=pb.READY, timeout=3.0):
        end = time.monotonic() + timeout
        last = None
        while time.monotonic() < end:
            last = self.call(
                "GetStatus", timeout=min(self.timeout, max(0.01, end - time.monotonic()))
            )
            if last.state == state:
                return last
            time.sleep(0.01)
        raise TimeoutError(f"expected {pb.State.Name(state)}; last status: {last}")

    def telemetry(self):
        telemetry = self.call("GetTelemetry")
        values = (
            telemetry.voltage_v,
            telemetry.module_temperature_c,
            telemetry.laser_temperature_c,
            telemetry.tx_power_dbm,
            telemetry.rx_power_dbm,
            telemetry.bias_current_ma,
        )
        if not telemetry.valid or not all(math.isfinite(value) for value in values):
            raise ValueError("invalid simulated telemetry")
        return telemetry

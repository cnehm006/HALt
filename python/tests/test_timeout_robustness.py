import time
from concurrent.futures import ThreadPoolExecutor

import grpc
import pytest
from halt.generated import halt_pb2 as pb


@pytest.mark.timeout
def test_rpc_timeout(client):
    client.call("InjectFault", pb.FaultRequest(fault=pb.COMMUNICATION_TIMEOUT))
    with pytest.raises(grpc.RpcError) as error:
        client.call("Ping", timeout=0.03)
    assert error.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
    assert client.call("GetStatus").fault == pb.COMMUNICATION_TIMEOUT


@pytest.mark.timeout
def test_instrument_timeout(client):
    with pytest.raises(grpc.RpcError) as error:
        client.call("MeasurePower", pb.MeterRequest(simulate_timeout=True), timeout=0.03)
    assert error.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
    assert client.call("MeasurePower", pb.MeterRequest(channel=pb.RX)).power_dbm == -5


@pytest.mark.timeout
def test_instrument_error(client):
    with pytest.raises(grpc.RpcError) as error:
        client.call("MeasurePower", pb.MeterRequest(simulate_error=True))
    assert error.value.code() == grpc.StatusCode.UNAVAILABLE


@pytest.mark.timeout
@pytest.mark.recovery
def test_recovery_after_timeout(client):
    client.call("InjectFault", pb.FaultRequest(fault=pb.COMMUNICATION_TIMEOUT))
    with pytest.raises(grpc.RpcError):
        client.call("GetTelemetry", timeout=0.02)
    client.call("ClearFault")
    client.wait_state()
    assert client.telemetry().valid
    assert client.call("Ping").identity.startswith("HALt")


@pytest.mark.robustness
@pytest.mark.parametrize(
    "method,value",
    [
        ("SetAttenuation", -0.001),
        ("SetAttenuation", 60.001),
        ("SetAttenuation", float("nan")),
        ("SetAttenuation", float("inf")),
        ("SetTemperature", -40.001),
        ("SetTemperature", 125.001),
        ("SetTemperature", float("nan")),
        ("SetTemperature", float("-inf")),
    ],
)
def test_invalid_environment_inputs(client, method, value):
    with pytest.raises(grpc.RpcError) as error:
        client.call(method, pb.Scalar(value=value))
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    data = client.telemetry()
    assert data.rx_power_dbm == -5
    assert data.module_temperature_c == 25


@pytest.mark.robustness
@pytest.mark.parametrize(
    "method,message",
    [
        ("SetMode", pb.ModeRequest(mode=99)),
        ("SetMode", pb.ModeRequest(mode=256)),
        ("SetMode", pb.ModeRequest(mode=-1)),
        ("InjectFault", pb.FaultRequest(fault=99)),
        ("InjectFault", pb.FaultRequest(fault=pb.NONE)),
        ("MeasurePower", pb.MeterRequest(channel=99)),
        ("MeasurePower", pb.MeterRequest(channel=256)),
        ("MeasurePower", pb.MeterRequest(noise_stddev_db=float("nan"))),
        ("MeasurePower", pb.MeterRequest(noise_stddev_db=-1)),
    ],
)
def test_invalid_enums_and_meter_noise(client, method, message):
    with pytest.raises(grpc.RpcError) as error:
        client.call(method, message)
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert client.call("GetStatus").state == pb.READY


@pytest.mark.robustness
def test_malformed_protobuf_does_not_crash_server(client):
    raw = client.channel.unary_unary("/halt.rpc.DeviceControl/SetMode")
    with pytest.raises(grpc.RpcError):
        raw(b"\xff\xff\xff", timeout=1)
    assert client.call("Ping").identity.startswith("HALt")


@pytest.mark.robustness
def test_oversized_request_is_bounded(client):
    raw = client.channel.unary_unary("/halt.rpc.DeviceControl/SetMode")
    with pytest.raises(grpc.RpcError) as error:
        raw(b"x" * (65 * 1024), timeout=1)
    assert error.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED
    assert client.call("GetStatus").state == pb.READY


@pytest.mark.timeout
@pytest.mark.concurrency
def test_pending_timeout_does_not_block_recovery(client):
    client.call("InjectFault", pb.FaultRequest(fault=pb.COMMUNICATION_TIMEOUT))
    sequence = client.call("GetEvents").events[-1].sequence
    pending = client.rpc.GetTelemetry.future(pb.Empty(), timeout=0.2)
    end = time.monotonic() + 1
    while time.monotonic() < end:
        events = client.call("GetEvents").events
        if any(e.sequence > sequence and e.message == "telemetry response delayed" for e in events):
            break
        time.sleep(0.005)
    else:
        pytest.fail("delayed request never entered the server")
    assert not pending.done()
    client.call("ClearFault", timeout=0.1)
    client.wait_state()
    with pytest.raises(grpc.RpcError) as error:
        pending.result()
    assert error.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
    assert client.telemetry().valid


@pytest.mark.concurrency
def test_concurrent_snapshot_consistency(client):
    def work(index):
        for step in range(15):
            if index % 2:
                client.call("EnableTransmitter" if step % 2 else "DisableTransmitter")
            data = client.telemetry()
            assert data.tx_power_dbm == (0 if data.status.tx_enabled else -80)
            assert data.bias_current_ma == (35 if data.status.tx_enabled else 0)
            assert data.status.state == pb.READY

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(work, range(8)))


@pytest.mark.robustness
def test_event_log_is_ordered_and_bounded(client):
    for value in range(530):
        client.call("SetAttenuation", pb.Scalar(value=value % 10))
    events = client.call("GetEvents").events
    assert len(events) == 512
    sequences = [event.sequence for event in events]
    assert sequences == sorted(set(sequences))
    assert all(event.timestamp.endswith("Z") for event in events)

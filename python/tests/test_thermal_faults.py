import math

import grpc
import pytest
from halt.generated import halt_pb2 as pb


@pytest.mark.thermal
@pytest.mark.parametrize(
    "temperature,unsafe",
    [(-40, False), (25, False), (84.999, False), (85, True), (85.001, True), (125, True)],
)
def test_temperature_threshold(client, temperature, unsafe):
    client.call("EnableTransmitter")
    status = client.call("SetTemperature", pb.Scalar(value=temperature))
    assert ("OVER_TEMPERATURE" in status.alarms) == unsafe
    assert status.state == (pb.FAULT if unsafe else pb.READY)
    assert status.tx_enabled != unsafe
    assert client.telemetry().module_temperature_c == temperature


@pytest.mark.thermal
@pytest.mark.recovery
def test_temperature_recovery(client):
    client.call("SetTemperature", pb.Scalar(value=90))
    assert client.call("ClearFault").state == pb.FAULT
    client.call("SetTemperature", pb.Scalar(value=30))
    assert client.call("GetStatus").state == pb.FAULT  # latched until acknowledged
    assert client.call("ClearFault").state == pb.RECOVERING
    assert not client.wait_state().tx_enabled


@pytest.mark.thermal
@pytest.mark.recovery
def test_reset_cannot_bypass_external_temperature(client):
    client.call("SetTemperature", pb.Scalar(value=100))
    client.call("Reset")
    client.wait_state(pb.FAULT)
    with pytest.raises(grpc.RpcError) as error:
        client.call("EnableTransmitter")
    assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION


@pytest.mark.fault
@pytest.mark.recovery
@pytest.mark.parametrize(
    "fault",
    [
        pb.SENSOR_FAILURE,
        pb.COMMUNICATION_TIMEOUT,
        pb.OVER_TEMPERATURE,
        pb.INVALID_TELEMETRY,
        pb.LASER_FAULT,
        pb.POWER_SUPPLY_FAULT,
    ],
)
def test_fault_detection_interlock_and_clear(client, fault):
    client.call("EnableTransmitter")
    status = client.call("InjectFault", pb.FaultRequest(fault=fault))
    assert status.fault == fault
    assert pb.Fault.Name(fault) in status.alarms
    assert status.state == pb.FAULT
    assert status.mode == pb.SAFE
    assert not status.tx_enabled
    with pytest.raises(grpc.RpcError) as error:
        client.call("EnableTransmitter")
    assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    client.call("ClearFault")
    recovered = client.wait_state()
    assert recovered.fault == pb.NONE
    assert not recovered.alarms
    assert not recovered.tx_enabled
    client.call("EnableTransmitter")
    assert client.telemetry().tx_power_dbm == 0


@pytest.mark.fault
@pytest.mark.parametrize(
    "fault,field",
    [(pb.SENSOR_FAILURE, "module_temperature_c"), (pb.INVALID_TELEMETRY, "voltage_v")],
)
def test_invalid_telemetry_rejected_by_client(client, fault, field):
    client.call("InjectFault", pb.FaultRequest(fault=fault))
    raw = client.call("GetTelemetry")
    assert not raw.valid
    assert math.isnan(getattr(raw, field))
    with pytest.raises(ValueError, match="invalid simulated telemetry"):
        client.telemetry()


@pytest.mark.fault
@pytest.mark.recovery
def test_reset_after_fault_and_reinitialization(client):
    client.call("InjectFault", pb.FaultRequest(fault=pb.LASER_FAULT))
    client.call("Reset")
    assert client.wait_state().fault == pb.NONE
    assert client.telemetry().valid


@pytest.mark.fault
@pytest.mark.parametrize(
    "fault,field,expected",
    [(pb.POWER_SUPPLY_FAULT, "voltage_v", 2.5), (pb.OVER_TEMPERATURE, "module_temperature_c", 95)],
)
def test_fault_changes_physical_model(client, fault, field, expected):
    client.call("InjectFault", pb.FaultRequest(fault=fault))
    assert getattr(client.call("GetTelemetry"), field) == pytest.approx(expected)

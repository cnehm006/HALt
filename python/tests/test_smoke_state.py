import time

import grpc
import pytest
from halt.generated import halt_pb2 as pb


@pytest.mark.smoke
def test_device_ping(client):
    assert "SIMULATED OPTICAL" in client.call("Ping").identity


@pytest.mark.smoke
def test_device_status(client):
    status = client.call("GetStatus")
    assert status.state == pb.READY
    assert status.mode == pb.NORMAL
    assert status.fault == pb.NONE
    assert not status.alarms


@pytest.mark.smoke
def test_telemetry_fields_present(client):
    data = client.telemetry()
    assert data.voltage_v == pytest.approx(3.3)
    assert data.module_temperature_c == pytest.approx(25)
    assert data.laser_temperature_c == pytest.approx(25)
    assert data.tx_power_dbm == -80
    assert data.rx_power_dbm == -5
    assert data.bias_current_ma == 0
    assert data.status.link_up


@pytest.mark.state
def test_boot_to_ready(client):
    before = client.call("GetEvents").events[-1].sequence
    assert client.call("Reset").state == pb.BOOTING
    client.wait_state()
    transitions = [e.message for e in client.call("GetEvents").events if e.sequence > before]
    assert "BOOTING -> INITIALIZING" in transitions
    assert "INITIALIZING -> READY" in transitions


@pytest.mark.state
def test_valid_mode_change(client):
    client.call("EnableTransmitter")
    assert client.call("SetMode", pb.ModeRequest(mode=pb.SAFE)).state == pb.STANDBY
    assert not client.call("GetStatus").tx_enabled
    assert client.call("SetMode", pb.ModeRequest(mode=pb.NORMAL)).state == pb.READY


@pytest.mark.state
def test_illegal_state_transition(client):
    client.call("SetMode", pb.ModeRequest(mode=pb.SAFE))
    with pytest.raises(grpc.RpcError) as error:
        client.call("EnableTransmitter")
    assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    assert client.call("GetStatus").state == pb.STANDBY


@pytest.mark.recovery
def test_reset_returns_device_to_known_state(client):
    client.call("EnableTransmitter")
    client.call("Reset")
    status = client.wait_state()
    assert not status.tx_enabled
    assert status.mode == pb.NORMAL
    assert status.fault == pb.NONE


@pytest.mark.state
def test_uptime_progresses(client):
    start = client.call("GetStatus").uptime_ms
    time.sleep(0.04)
    assert client.call("GetStatus").uptime_ms > start

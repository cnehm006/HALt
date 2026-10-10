import statistics

import pytest
from halt.generated import halt_pb2 as pb

pytestmark = pytest.mark.link


def test_tx_enable_produces_output_power(client):
    client.call("EnableTransmitter")
    data = client.telemetry()
    assert data.tx_power_dbm == pytest.approx(0)
    assert data.bias_current_ma == pytest.approx(35)
    assert data.laser_temperature_c > data.module_temperature_c
    assert client.call("MeasurePower", pb.MeterRequest(channel=pb.TX)).power_dbm == 0


def test_tx_disable_removes_output_power(client):
    client.call("EnableTransmitter")
    client.call("DisableTransmitter")
    assert client.telemetry().tx_power_dbm == -80
    assert client.telemetry().bias_current_ma == 0


def test_rx_power_changes_with_attenuation(client):
    baseline = client.telemetry().rx_power_dbm
    client.call("SetAttenuation", pb.Scalar(value=7.5))
    assert client.telemetry().rx_power_dbm == pytest.approx(baseline - 7.5)
    assert client.call("MeasurePower", pb.MeterRequest(channel=pb.RX)).power_dbm == pytest.approx(
        -12.5
    )


@pytest.mark.parametrize(
    "attenuation,up", [(0, True), (14.999, True), (15, True), (15.001, False), (60, False)]
)
def test_loss_of_signal_threshold(client, attenuation, up):
    status = client.call("SetAttenuation", pb.Scalar(value=attenuation))
    assert status.link_up == up
    assert ("RX_LOS" in status.alarms) != up
    assert status.state == (pb.READY if up else pb.DEGRADED)


@pytest.mark.recovery
def test_link_recovers_when_signal_returns(client):
    client.call("SetAttenuation", pb.Scalar(value=30))
    assert not client.call("GetStatus").link_up
    status = client.call("SetAttenuation", pb.Scalar(value=2))
    assert status.link_up
    assert "RX_LOS" not in status.alarms


def test_power_meter_configurable_noise(client):
    readings = [
        client.call("MeasurePower", pb.MeterRequest(channel=pb.RX, noise_stddev_db=0.1)).power_dbm
        for _ in range(100)
    ]
    assert len(set(readings)) > 90
    assert statistics.mean(readings) == pytest.approx(-5, abs=0.05)
    assert 0.06 < statistics.stdev(readings) < 0.15

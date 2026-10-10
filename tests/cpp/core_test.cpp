#include "halt/device.hpp"
#include "halt/instruments.hpp"
#include <gtest/gtest.h>
#include <limits>

namespace {
TEST(StateMachine, LegalAndIllegalEdges) {
  using halt::State;
  EXPECT_TRUE(halt::legal_transition(State::PoweredOff, State::Booting));
  EXPECT_TRUE(halt::legal_transition(State::Booting, State::Initializing));
  EXPECT_TRUE(halt::legal_transition(State::Initializing, State::Ready));
  EXPECT_TRUE(halt::legal_transition(State::Fault, State::Recovering));
  EXPECT_FALSE(halt::legal_transition(State::PoweredOff, State::Ready));
  EXPECT_FALSE(halt::legal_transition(State::Fault, State::Ready));
  EXPECT_FALSE(halt::legal_transition(State::Standby, State::Recovering));
}
TEST(Validation, RejectsNonFiniteAndOutOfRange) {
  EXPECT_TRUE(halt::finite_in_range(0, 0, 60));
  EXPECT_TRUE(halt::finite_in_range(60, 0, 60));
  EXPECT_FALSE(halt::finite_in_range(-0.001, 0, 60));
  EXPECT_FALSE(halt::finite_in_range(60.001, 0, 60));
  EXPECT_FALSE(halt::finite_in_range(std::numeric_limits<double>::quiet_NaN(), 0, 60));
  EXPECT_FALSE(halt::finite_in_range(std::numeric_limits<double>::infinity(), 0, 60));
}
// A fake implementing only the HAL proves the instrument has no simulator dependency.
class FixedTelemetry final : public halt::ITelemetryProvider {
public:
  halt::Snapshot value;
  halt::Snapshot snapshot() const override { return value; }
};
TEST(Instrument, UsesHalAndSeparatesChannels) {
  FixedTelemetry source;
  source.value.tx_power_dbm = 1;
  source.value.rx_power_dbm = -12;
  halt::OpticalPowerMeter meter(source);
  EXPECT_DOUBLE_EQ(meter.measure(halt::Channel::Tx, 0), 1);
  EXPECT_DOUBLE_EQ(meter.measure(halt::Channel::Rx, 0), -12);
  source.value.valid = false;
  EXPECT_THROW(meter.measure(halt::Channel::Tx, 0), std::runtime_error);
}
TEST(Instrument, RejectsInvalidNoiseAndChannel) {
  FixedTelemetry source;
  halt::OpticalPowerMeter meter(source);
  EXPECT_THROW(meter.measure(halt::Channel::Rx, -1), std::invalid_argument);
  EXPECT_THROW(meter.measure(static_cast<halt::Channel>(99), 0), std::invalid_argument);
}
TEST(Device, InputsAndDisabledOutput) {
  halt::EventLog log;
  halt::SimulatedDevice device(log);
  EXPECT_FALSE(device.snapshot().tx_enabled);
  EXPECT_DOUBLE_EQ(device.snapshot().tx_power_dbm, -80);
  EXPECT_THROW(device.set_mode(static_cast<halt::Mode>(99)), std::invalid_argument);
  EXPECT_THROW(device.inject_fault(static_cast<halt::Fault>(99)), std::invalid_argument);
  EXPECT_THROW(device.set_attenuation(-1), std::invalid_argument);
  EXPECT_THROW(device.set_temperature(126), std::invalid_argument);
}
TEST(Device, AttenuationCalculationAndThreshold) {
  halt::EventLog log;
  halt::SimulatedDevice device(log);
  device.set_attenuation(15);
  EXPECT_DOUBLE_EQ(device.snapshot().rx_power_dbm, halt::kLosThresholdDbm);
  EXPECT_TRUE(device.snapshot().alarms.empty());
  device.set_attenuation(15.001);
  EXPECT_EQ(device.snapshot().alarms.at(0), "RX_LOS");
}
TEST(Device, ThermalThresholdIsInclusive) {
  halt::EventLog log;
  halt::SimulatedDevice device(log);
  device.set_temperature(84.999);
  EXPECT_TRUE(device.snapshot().alarms.empty());
  device.set_temperature(85);
  EXPECT_EQ(device.snapshot().alarms.at(0), "OVER_TEMPERATURE");
  EXPECT_FALSE(device.snapshot().tx_enabled);
}
TEST(EventLog, KeepsNewest512Events) {
  halt::EventLog log;
  for (int i = 0; i < 520; ++i)
    log.write("INFO", "TEST", "bounded event");
  const auto events = log.read();
  EXPECT_EQ(events.size(), 512U);
  EXPECT_EQ(events.front().sequence, 9U);
  EXPECT_EQ(events.back().sequence, 520U);
}
} // namespace

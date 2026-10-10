#include "halt/device.hpp"
#include <limits>
#include <stdexcept>

namespace halt {
using namespace std::chrono_literals;
SimulatedDevice::SimulatedDevice(EventLog &log) : log_(log) {
  reset();
  worker_ = std::thread(&SimulatedDevice::run, this);
}
SimulatedDevice::~SimulatedDevice() {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    stopping_ = true;
  }
  wake_.notify_all();
  worker_.join();
}
Snapshot SimulatedDevice::snapshot() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return data_;
}
void SimulatedDevice::transition(State next) {
  if (!legal_transition(data_.state, next))
    throw std::logic_error("illegal device transition");
  log_.write("INFO", "DEVICE", std::string(state_name(data_.state)) + " -> " + state_name(next));
  data_.state = next;
  entered_ = Clock::now();
}
void SimulatedDevice::reset() {
  std::lock_guard<std::mutex> lock(mutex_);
  // External lab conditions persist across reset; an unsafe environment cannot be bypassed.
  data_.fault = Fault::None;
  data_.mode = Mode::Normal;
  data_.tx_enabled = false;
  started_ = Clock::now();
  transition(State::Booting);
  update();
}
void SimulatedDevice::set_mode(Mode mode) {
  if (mode != Mode::Normal && mode != Mode::Safe)
    throw std::invalid_argument("unknown mode");
  std::lock_guard<std::mutex> lock(mutex_);
  if (data_.state != State::Ready && data_.state != State::Degraded &&
      data_.state != State::Standby)
    throw std::logic_error("mode change requires an operational device");
  data_.mode = mode;
  if (mode == Mode::Safe) {
    data_.tx_enabled = false;
    if (data_.state != State::Standby)
      transition(State::Standby);
  } else if (data_.state == State::Standby)
    transition(State::Ready);
  update();
}
void SimulatedDevice::enable_tx(bool enabled) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (enabled && (data_.mode != Mode::Normal ||
                  (data_.state != State::Ready && data_.state != State::Degraded)))
    throw std::logic_error("transmitter interlock: device is not operational");
  data_.tx_enabled = enabled;
  log_.write("INFO", "DEVICE", enabled ? "TX enabled" : "TX disabled");
  update();
}
void SimulatedDevice::inject_fault(Fault fault) {
  if (fault < Fault::SensorFailure || fault > Fault::PowerSupplyFault)
    throw std::invalid_argument("unknown fault");
  std::lock_guard<std::mutex> lock(mutex_);
  if (data_.state != State::Ready && data_.state != State::Degraded &&
      data_.state != State::Standby)
    throw std::logic_error(
        "fault injection requires operational state; clear existing fault first");
  data_.fault = fault;
  log_.write("WARN", "DEVICE", "fault injected: " + std::to_string(static_cast<int>(fault)));
  update();
}
void SimulatedDevice::clear_fault() {
  std::lock_guard<std::mutex> lock(mutex_);
  data_.fault = Fault::None;
  if (data_.state == State::Fault && ambient_c_ < kThermalThresholdC) {
    data_.mode = Mode::Normal;
    transition(State::Recovering);
  }
  update();
}
void SimulatedDevice::set_attenuation(double db) {
  if (!finite_in_range(db, 0, 60))
    throw std::invalid_argument("attenuation must be finite and in [0,60] dB");
  std::lock_guard<std::mutex> lock(mutex_);
  attenuation_db_ = db;
  log_.write("INFO", "INSTRUMENT", "attenuation_db=" + std::to_string(db));
  update();
}
void SimulatedDevice::set_temperature(double celsius) {
  if (!finite_in_range(celsius, -40, 125))
    throw std::invalid_argument("temperature must be finite and in [-40,125] C");
  std::lock_guard<std::mutex> lock(mutex_);
  ambient_c_ = celsius;
  log_.write("INFO", "INSTRUMENT", "temperature_c=" + std::to_string(celsius));
  update();
}
void SimulatedDevice::update() {
  const auto now = Clock::now();
  data_.uptime_ms = static_cast<std::uint64_t>(
      std::chrono::duration_cast<std::chrono::milliseconds>(now - started_).count());
  if (now - entered_ >= 100ms) {
    if (data_.state == State::Booting)
      transition(State::Initializing);
    else if (data_.state == State::Initializing || data_.state == State::Recovering)
      transition(State::Ready);
  }
  const auto old_alarms = data_.alarms;
  data_.alarms.clear();
  data_.valid = true;
  data_.module_temperature_c = data_.fault == Fault::OverTemperature ? 95.0 : ambient_c_;
  data_.voltage_v = data_.fault == Fault::PowerSupplyFault ? 2.5 : 3.3;
  data_.rx_power_dbm = -5.0 - attenuation_db_;
  if (data_.rx_power_dbm < kLosThresholdDbm)
    data_.alarms.emplace_back("RX_LOS");
  if (data_.module_temperature_c >= kThermalThresholdC)
    data_.alarms.emplace_back("OVER_TEMPERATURE");
  if (data_.fault == Fault::SensorFailure) {
    data_.alarms.emplace_back("SENSOR_FAILURE");
    data_.valid = false;
  }
  if (data_.fault == Fault::InvalidTelemetry) {
    data_.alarms.emplace_back("INVALID_TELEMETRY");
    data_.valid = false;
  }
  if (data_.fault == Fault::LaserFault)
    data_.alarms.emplace_back("LASER_FAULT");
  if (data_.fault == Fault::PowerSupplyFault)
    data_.alarms.emplace_back("POWER_SUPPLY_FAULT");
  if (data_.fault == Fault::CommunicationTimeout)
    data_.alarms.emplace_back("COMMUNICATION_TIMEOUT");
  const bool unsafe =
      data_.module_temperature_c >= kThermalThresholdC || data_.fault != Fault::None;
  if (unsafe) {
    data_.tx_enabled = false;
    data_.mode = Mode::Safe;
    if (data_.state != State::Fault && data_.state != State::Booting)
      transition(State::Fault);
  } else {
    if (data_.state == State::Ready && data_.rx_power_dbm < kLosThresholdDbm)
      transition(State::Degraded);
    else if (data_.state == State::Degraded && data_.rx_power_dbm >= kLosThresholdDbm)
      transition(State::Ready);
  }
  data_.tx_power_dbm = data_.tx_enabled ? 0.0 : -80.0;
  data_.bias_current_ma = data_.tx_enabled ? 35.0 : 0.0;
  data_.laser_temperature_c = data_.module_temperature_c + (data_.tx_enabled ? 3.0 : 0.0);
  data_.link_up = data_.state == State::Ready && data_.mode == Mode::Normal &&
                  data_.rx_power_dbm >= kLosThresholdDbm;
  // Deliberately corrupt a field, with validity and interlock asserted independently.
  if (data_.fault == Fault::InvalidTelemetry)
    data_.voltage_v = std::numeric_limits<double>::quiet_NaN();
  if (data_.fault == Fault::SensorFailure)
    data_.module_temperature_c = std::numeric_limits<double>::quiet_NaN();
  if (old_alarms != data_.alarms) {
    std::string message = "alarms=";
    for (const auto &alarm : data_.alarms)
      message += alarm + " ";
    log_.write(data_.alarms.empty() ? "INFO" : "WARN", "DEVICE", message);
  }
}
void SimulatedDevice::run() {
  std::unique_lock<std::mutex> lock(mutex_);
  while (!wake_.wait_for(lock, 10ms, [this] { return stopping_; }))
    update();
}
} // namespace halt

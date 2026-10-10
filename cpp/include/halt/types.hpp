#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace halt {
enum class State { PoweredOff, Booting, Standby, Initializing, Ready, Degraded, Fault, Recovering };
enum class Mode { Normal, Safe };
enum class Fault {
  None,
  SensorFailure,
  CommunicationTimeout,
  OverTemperature,
  InvalidTelemetry,
  LaserFault,
  PowerSupplyFault
};
struct Snapshot {
  State state{State::PoweredOff};
  Mode mode{Mode::Normal};
  Fault fault{Fault::None};
  bool link_up{false}, tx_enabled{false}, valid{true};
  std::uint64_t uptime_ms{0};
  double voltage_v{3.3}, module_temperature_c{25}, laser_temperature_c{25};
  double tx_power_dbm{-80}, rx_power_dbm{-5}, bias_current_ma{0};
  std::vector<std::string> alarms;
};
constexpr double kLosThresholdDbm = -20.0;
constexpr double kThermalThresholdC = 85.0;
bool legal_transition(State from, State to);
const char *state_name(State state);
bool finite_in_range(double value, double low, double high);
} // namespace halt

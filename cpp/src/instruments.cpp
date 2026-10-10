#include "halt/instruments.hpp"
#include <stdexcept>

namespace halt {
double OpticalPowerMeter::measure(Channel channel, double noise_stddev_db) {
  if (channel != Channel::Tx && channel != Channel::Rx)
    throw std::invalid_argument("unknown optical channel");
  if (!finite_in_range(noise_stddev_db, 0, 2))
    throw std::invalid_argument("noise standard deviation must be in [0,2] dB");
  const auto telemetry = source_.snapshot();
  if (!telemetry.valid)
    throw std::runtime_error("measurement source is invalid");
  std::lock_guard<std::mutex> lock(mutex_);
  const double noise =
      noise_stddev_db == 0 ? 0 : std::normal_distribution<double>(0, noise_stddev_db)(random_);
  return (channel == Channel::Tx ? telemetry.tx_power_dbm : telemetry.rx_power_dbm) + noise;
}
} // namespace halt

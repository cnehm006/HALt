#pragma once
#include "halt/hal.hpp"
#include <mutex>
#include <random>

namespace halt {
enum class Channel { Tx, Rx };
class IInstrument {
public:
  virtual ~IInstrument() = default;
  virtual const char *identity() const = 0;
};
class OpticalPowerMeter final : public IInstrument {
public:
  explicit OpticalPowerMeter(const ITelemetryProvider &source) : source_(source), random_(42) {}
  const char *identity() const override { return "HALt simulated optical power meter"; }
  double measure(Channel channel, double noise_stddev_db);

private:
  const ITelemetryProvider &source_;
  std::mutex mutex_;
  std::mt19937 random_;
};
class OpticalAttenuator final : public IInstrument {
public:
  explicit OpticalAttenuator(ISimulatedEnvironment &environment) : environment_(environment) {}
  const char *identity() const override { return "HALt simulated optical attenuator"; }
  void set(double db) { environment_.set_attenuation(db); }

private:
  ISimulatedEnvironment &environment_;
};
} // namespace halt

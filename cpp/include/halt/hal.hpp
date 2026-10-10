#pragma once
#include "halt/types.hpp"

namespace halt {
// The service depends on this contract, never on SimulatedDevice internals.
class ITelemetryProvider {
public:
  virtual ~ITelemetryProvider() = default;
  virtual Snapshot snapshot() const = 0;
};
class IDevice : public ITelemetryProvider {
public:
  virtual void reset() = 0;
  virtual void set_mode(Mode mode) = 0;
  virtual void enable_tx(bool enabled) = 0;
  virtual void inject_fault(Fault fault) = 0;
  virtual void clear_fault() = 0;
};
// Simulator-only environmental inputs are deliberately separate from device control.
class ISimulatedEnvironment {
public:
  virtual ~ISimulatedEnvironment() = default;
  virtual void set_attenuation(double db) = 0;
  virtual void set_temperature(double celsius) = 0;
};
} // namespace halt

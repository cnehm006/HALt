#pragma once
#include "halt/events.hpp"
#include "halt/hal.hpp"
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>

namespace halt {
class SimulatedDevice final : public IDevice, public ISimulatedEnvironment {
public:
  explicit SimulatedDevice(EventLog &log);
  ~SimulatedDevice() override;
  Snapshot snapshot() const override;
  void reset() override;
  void set_mode(Mode mode) override;
  void enable_tx(bool enabled) override;
  void inject_fault(Fault fault) override;
  void clear_fault() override;
  void set_attenuation(double db) override;
  void set_temperature(double celsius) override;

private:
  using Clock = std::chrono::steady_clock;
  void transition(State next);
  void update(); // Caller holds mutex_.
  void run();
  EventLog &log_;
  mutable std::mutex mutex_;
  std::condition_variable wake_;
  bool stopping_{false};
  Snapshot data_;
  double attenuation_db_{0}, ambient_c_{25};
  Clock::time_point started_{Clock::now()}, entered_{started_};
  std::thread worker_;
};
} // namespace halt

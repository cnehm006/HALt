#include "halt/types.hpp"
#include <cmath>

namespace halt {
bool finite_in_range(double value, double low, double high) {
  return std::isfinite(value) && value >= low && value <= high;
}
const char *state_name(State state) {
  switch (state) {
  case State::PoweredOff:
    return "POWERED_OFF";
  case State::Booting:
    return "BOOTING";
  case State::Standby:
    return "STANDBY";
  case State::Initializing:
    return "INITIALIZING";
  case State::Ready:
    return "READY";
  case State::Degraded:
    return "DEGRADED";
  case State::Fault:
    return "FAULT";
  case State::Recovering:
    return "RECOVERING";
  }
  return "UNKNOWN";
}
bool legal_transition(State from, State to) {
  if (to == State::Booting)
    return true; // Reset is legal from every state.
  switch (from) {
  case State::Booting:
    return to == State::Initializing;
  case State::Initializing:
    return to == State::Ready || to == State::Fault;
  case State::Ready:
    return to == State::Standby || to == State::Degraded || to == State::Fault;
  case State::Standby:
    return to == State::Ready || to == State::Fault;
  case State::Degraded:
    return to == State::Ready || to == State::Standby || to == State::Fault;
  case State::Fault:
    return to == State::Recovering;
  case State::Recovering:
    return to == State::Ready || to == State::Fault;
  case State::PoweredOff:
    return false;
  }
  return false;
}
} // namespace halt

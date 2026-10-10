#include "halt/events.hpp"
#include <chrono>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <sstream>

namespace halt {
void EventLog::write(const std::string &level, const std::string &component,
                     const std::string &message) {
  std::lock_guard<std::mutex> lock(mutex_);
  const auto now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
  std::tm utc{};
#ifdef _WIN32
  gmtime_s(&utc, &now);
#else
  gmtime_r(&now, &utc);
#endif
  std::ostringstream timestamp;
  timestamp << std::put_time(&utc, "%Y-%m-%dT%H:%M:%SZ");
  events_.push_back({++sequence_, timestamp.str(), level, component, message});
  if (events_.size() > 512)
    events_.pop_front();
  std::cout << "{\"sequence\":" << sequence_ << ",\"timestamp\":" << std::quoted(timestamp.str())
            << ",\"level\":" << std::quoted(level) << ",\"component\":" << std::quoted(component)
            << ",\"message\":" << std::quoted(message) << "}\n"
            << std::flush;
}
std::vector<Event> EventLog::read() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return {events_.begin(), events_.end()};
}
} // namespace halt

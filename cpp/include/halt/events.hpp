#pragma once
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include <vector>

namespace halt {
struct Event {
  std::uint64_t sequence;
  std::string timestamp, level, component, message;
};
class EventLog {
public:
  void write(const std::string &level, const std::string &component, const std::string &message);
  std::vector<Event> read() const;

private:
  mutable std::mutex mutex_;
  std::deque<Event> events_;
  std::uint64_t sequence_{0};
};
} // namespace halt

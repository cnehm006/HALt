#include "halt/service.hpp"
#include <chrono>
#include <stdexcept>
#include <thread>

namespace halt {
namespace {
template <typename Function> grpc::Status guard(Function action) {
  try {
    action();
    return grpc::Status::OK;
  } catch (const std::invalid_argument &error) {
    return {grpc::StatusCode::INVALID_ARGUMENT, error.what()};
  } catch (const std::logic_error &error) {
    return {grpc::StatusCode::FAILED_PRECONDITION, error.what()};
  } catch (const std::runtime_error &error) {
    return {grpc::StatusCode::UNAVAILABLE, error.what()};
  } catch (const std::exception &) {
    return {grpc::StatusCode::INTERNAL, "unexpected service error"};
  }
}
grpc::Status delayed_response(grpc::ServerContext *context) {
  const auto end = std::chrono::steady_clock::now() + std::chrono::milliseconds(300);
  while (std::chrono::steady_clock::now() < end) {
    if (context->IsCancelled())
      return {grpc::StatusCode::CANCELLED, "request cancelled"};
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  return {grpc::StatusCode::UNAVAILABLE, "simulated communication timeout"};
}
} // namespace
void ControlService::fill_status(const Snapshot &s, rpc::Status *out) {
  out->set_state(static_cast<rpc::State>(s.state));
  out->set_mode(static_cast<rpc::Mode>(s.mode));
  out->set_fault(static_cast<rpc::Fault>(s.fault));
  out->set_link_up(s.link_up);
  out->set_tx_enabled(s.tx_enabled);
  out->set_uptime_ms(s.uptime_ms);
  for (const auto &alarm : s.alarms)
    out->add_alarms(alarm);
}
grpc::Status ControlService::Ping(grpc::ServerContext *context, const rpc::Empty *,
                                  rpc::Pong *out) {
  if (device_.snapshot().fault == Fault::CommunicationTimeout)
    return delayed_response(context);
  out->set_identity("HALt: GENERIC SIMULATED OPTICAL COMMUNICATIONS MODULE");
  return grpc::Status::OK;
}
grpc::Status ControlService::GetStatus(grpc::ServerContext *, const rpc::Empty *,
                                       rpc::Status *out) {
  fill_status(device_.snapshot(), out);
  return grpc::Status::OK;
}
grpc::Status ControlService::GetTelemetry(grpc::ServerContext *context, const rpc::Empty *,
                                          rpc::Telemetry *out) {
  const auto s = device_.snapshot();
  if (s.fault == Fault::CommunicationTimeout) {
    log_.write("WARN", "TRANSPORT", "telemetry response delayed");
    return delayed_response(context);
  }
  fill_status(s, out->mutable_status());
  out->set_voltage_v(s.voltage_v);
  out->set_module_temperature_c(s.module_temperature_c);
  out->set_laser_temperature_c(s.laser_temperature_c);
  out->set_tx_power_dbm(s.tx_power_dbm);
  out->set_rx_power_dbm(s.rx_power_dbm);
  out->set_bias_current_ma(s.bias_current_ma);
  out->set_valid(s.valid);
  return grpc::Status::OK;
}
grpc::Status ControlService::SetMode(grpc::ServerContext *, const rpc::ModeRequest *request,
                                     rpc::Status *out) {
  return guard([&] {
    device_.set_mode(static_cast<Mode>(request->mode()));
    fill_status(device_.snapshot(), out);
  });
}
grpc::Status ControlService::EnableTransmitter(grpc::ServerContext *, const rpc::Empty *,
                                               rpc::Status *out) {
  return guard([&] {
    device_.enable_tx(true);
    fill_status(device_.snapshot(), out);
  });
}
grpc::Status ControlService::DisableTransmitter(grpc::ServerContext *, const rpc::Empty *,
                                                rpc::Status *out) {
  return guard([&] {
    device_.enable_tx(false);
    fill_status(device_.snapshot(), out);
  });
}
grpc::Status ControlService::Reset(grpc::ServerContext *, const rpc::Empty *, rpc::Status *out) {
  return guard([&] {
    device_.reset();
    fill_status(device_.snapshot(), out);
  });
}
grpc::Status ControlService::InjectFault(grpc::ServerContext *, const rpc::FaultRequest *request,
                                         rpc::Status *out) {
  return guard([&] {
    device_.inject_fault(static_cast<Fault>(request->fault()));
    fill_status(device_.snapshot(), out);
  });
}
grpc::Status ControlService::ClearFault(grpc::ServerContext *, const rpc::Empty *,
                                        rpc::Status *out) {
  return guard([&] {
    device_.clear_fault();
    fill_status(device_.snapshot(), out);
  });
}
grpc::Status ControlService::SetAttenuation(grpc::ServerContext *, const rpc::Scalar *request,
                                            rpc::Status *out) {
  return guard([&] {
    attenuator_.set(request->value());
    fill_status(device_.snapshot(), out);
  });
}
grpc::Status ControlService::SetTemperature(grpc::ServerContext *, const rpc::Scalar *request,
                                            rpc::Status *out) {
  return guard([&] {
    environment_.set_temperature(request->value());
    fill_status(device_.snapshot(), out);
  });
}
grpc::Status ControlService::MeasurePower(grpc::ServerContext *context,
                                          const rpc::MeterRequest *request, rpc::Reading *out) {
  if (request->simulate_timeout())
    return delayed_response(context);
  if (request->simulate_error())
    return {grpc::StatusCode::UNAVAILABLE, "simulated instrument error"};
  return guard([&] {
    out->set_power_dbm(
        meter_.measure(static_cast<Channel>(request->channel()), request->noise_stddev_db()));
    out->set_instrument(meter_.identity());
    log_.write("INFO", "INSTRUMENT", "power_dbm=" + std::to_string(out->power_dbm()));
  });
}
grpc::Status ControlService::GetEvents(grpc::ServerContext *, const rpc::Empty *,
                                       rpc::Events *out) {
  for (const auto &event : log_.read()) {
    auto *entry = out->add_events();
    entry->set_sequence(event.sequence);
    entry->set_timestamp(event.timestamp);
    entry->set_level(event.level);
    entry->set_component(event.component);
    entry->set_message(event.message);
  }
  return grpc::Status::OK;
}
} // namespace halt

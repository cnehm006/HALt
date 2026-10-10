#pragma once
#include "halt.grpc.pb.h"
#include "halt/events.hpp"
#include "halt/hal.hpp"
#include "halt/instruments.hpp"
#include <grpcpp/grpcpp.h>

namespace halt {
class ControlService final : public rpc::DeviceControl::Service {
public:
  ControlService(IDevice &device, ISimulatedEnvironment &environment, EventLog &log)
      : device_(device), environment_(environment), log_(log), meter_(device),
        attenuator_(environment) {}
  grpc::Status Ping(grpc::ServerContext *, const rpc::Empty *, rpc::Pong *) override;
  grpc::Status GetStatus(grpc::ServerContext *, const rpc::Empty *, rpc::Status *) override;
  grpc::Status GetTelemetry(grpc::ServerContext *, const rpc::Empty *, rpc::Telemetry *) override;
  grpc::Status SetMode(grpc::ServerContext *, const rpc::ModeRequest *, rpc::Status *) override;
  grpc::Status EnableTransmitter(grpc::ServerContext *, const rpc::Empty *, rpc::Status *) override;
  grpc::Status DisableTransmitter(grpc::ServerContext *, const rpc::Empty *,
                                  rpc::Status *) override;
  grpc::Status Reset(grpc::ServerContext *, const rpc::Empty *, rpc::Status *) override;
  grpc::Status InjectFault(grpc::ServerContext *, const rpc::FaultRequest *,
                           rpc::Status *) override;
  grpc::Status ClearFault(grpc::ServerContext *, const rpc::Empty *, rpc::Status *) override;
  grpc::Status SetAttenuation(grpc::ServerContext *, const rpc::Scalar *, rpc::Status *) override;
  grpc::Status SetTemperature(grpc::ServerContext *, const rpc::Scalar *, rpc::Status *) override;
  grpc::Status MeasurePower(grpc::ServerContext *, const rpc::MeterRequest *,
                            rpc::Reading *) override;
  grpc::Status GetEvents(grpc::ServerContext *, const rpc::Empty *, rpc::Events *) override;

private:
  static void fill_status(const Snapshot &source, rpc::Status *target);
  IDevice &device_;
  ISimulatedEnvironment &environment_;
  EventLog &log_;
  OpticalPowerMeter meter_;
  OpticalAttenuator attenuator_;
};
} // namespace halt

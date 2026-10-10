#include "halt/device.hpp"
#include "halt/service.hpp"
#include <csignal>
#include <iostream>

namespace {
volatile std::sig_atomic_t stopped = 0;
void on_signal(int) { stopped = 1; }
} // namespace
int main(int argc, char **argv) {
  try {
    int requested_port = 50051;
    if (argc == 3 && std::string(argv[1]) == "--port") {
      std::size_t used = 0;
      const std::string argument(argv[2]);
      requested_port = std::stoi(argument, &used);
      if (used != argument.size() || requested_port < 0 || requested_port > 65535)
        throw std::invalid_argument("invalid port");
    } else if (argc != 1)
      throw std::invalid_argument("usage: halt_server [--port 0..65535]");
    halt::EventLog log;
    halt::SimulatedDevice device(log);
    halt::ControlService service(device, device, log);
    grpc::ServerBuilder builder;
    int port = 0;
    builder.SetMaxReceiveMessageSize(64 * 1024);
    builder.SetSyncServerOption(grpc::ServerBuilder::SyncServerOption::MAX_POLLERS, 8);
    builder.AddListeningPort("127.0.0.1:" + std::to_string(requested_port),
                             grpc::InsecureServerCredentials(), &port);
    builder.RegisterService(&service);
    auto server = builder.BuildAndStart();
    if (!server || port == 0)
      throw std::runtime_error("cannot bind loopback listener");
    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);
    // Machine-readable startup handshake; port 0 avoids parallel test collisions.
    log.write("INFO", "SERVER", "HALT_PORT=" + std::to_string(port));
    while (stopped == 0)
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    server->Shutdown(std::chrono::system_clock::now() + std::chrono::seconds(1));
    server->Wait();
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}

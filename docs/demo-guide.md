# A five-minute technical demonstration

Start the console using [web-console.md](web-console.md). Introduce it accurately: “This is a generic simulated optical module, implemented in C++, with Python validation over gRPC. The browser exposes the same engineering harness.”

## 1. Establish the control path

On Workbench, enable TX. Point out 0 dBm TX power, 35 mA laser bias, and the laser temperature offset. Explain that the browser sends an HTTP command, Python calls the typed gRPC method, and the C++ model produces the measurements. Disable TX to show the output returns to the simulated floor.

## 2. Cross an optical boundary

Apply 15 dB attenuation. RX is exactly -20 dBm and the receive link remains up. Apply 16 dB: RX becomes -21 dBm, the state becomes DEGRADED, and RX_LOS appears in the actual device log. Measure RX with the optical power meter. Return attenuation to 2 dB and observe automatic link recovery.

Explain the exact comparison: loss of signal is strictly below -20 dBm. The test suite parameterizes values on both sides and at the boundary. The receive path is independent of local TX.

## 3. Show an interlock and deliberate recovery

Enable TX, then set module temperature to 85 °C. TX shuts down and the device enters FAULT/SAFE. Try Enable TX: the C++ service rejects it with FAILED_PRECONDITION. Clear fault while still hot: the device stays faulted.

Return temperature to 25 °C and clear the fault. Watch RECOVERING become READY. TX remains disabled until explicitly enabled. Explain why reset does not erase an unsafe external temperature.

## 4. Demonstrate failures without hiding them

Inject Invalid telemetry. The voltage field becomes unavailable and the sample is explicitly marked invalid. Clear the fault. In the power meter, choose Simulate timeout and measure: the real RPC deadline produces DEADLINE_EXCEEDED. Choose Normal and measure again to demonstrate recovery.

## 5. Produce reviewable evidence

Open Validation and run Full validation. Controls lock while pytest uses the same module; Workbench still shows the changing state and actual events. Return to Validation to inspect the real per-test durations and totals. Expand provenance and download JUnit XML, pytest output, and the simulator log.

Explain that the browser does not supply success values. The runner derives them from pytest phase reports and process exit status, checks teardown completion, and preserves cancelled and failed executions. The codebase tests reporting using an actual deliberately failing pytest subprocess.

## Finish with the limitations

Open Architecture. Explain the HAL replacement seam and what physical hardware would require: documented transport, calibrated instruments, exclusive device access, real timing budgets, authorization, and independent safety mechanisms.

Avoid claiming physical optical performance, vendor compatibility, production firmware deployment, or hosted CI success without evidence. The strongest point is the reproducible test workflow and the ability to explain each boundary and failure mode.

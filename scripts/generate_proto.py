"""Generate Python bindings from the same contract used by CMake."""

from pathlib import Path

from grpc_tools import protoc

root = Path(__file__).resolve().parents[1]
output = root / "python" / "halt" / "generated"
output.mkdir(parents=True, exist_ok=True)
result = protoc.main(
    [
        "grpc_tools.protoc",
        f"-I{root / 'proto'}",
        f"--python_out={output}",
        f"--grpc_python_out={output}",
        str(root / "proto" / "halt.proto"),
    ]
)
if result:
    raise SystemExit(result)
# protoc emits sibling absolute imports; make the generated package relocatable.
stub = output / "halt_pb2_grpc.py"
stub.write_text(
    stub.read_text(encoding="utf-8").replace("import halt_pb2 as", "from . import halt_pb2 as"),
    encoding="utf-8",
)

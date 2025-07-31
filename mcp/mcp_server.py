import docker
from fastmcp import FastMCP
import shlex
from ui_connection import EmulatorState, get_ui_state

mcp = FastMCP(name="Mobile Cyber MCP", stateless_http=True)
docker_client = docker.from_env()
kali_container_name = "kali-container"
host_adb_server = "host.docker.internal:5037"

def get_kali():
    return docker_client.containers.get(kali_container_name)

@mcp.tool(description="Execute a terminal command. For adb commands, write 'adb shell ...'. ")
def execute_command(command: str) -> EmulatorState:
    try:
        container = get_kali()

        # Determine if the command is an ADB command
        if command.strip().startswith("adb"):
            # Prefix ADB server socket export
            full_cmd = f"export ADB_SERVER_SOCKET=tcp:{host_adb_server} && {command}"
            label = "ADB Command"
        else:
            full_cmd = command
            label = "Command"

        # Safely quote the entire command for bash -c execution inside Docker
        result = container.exec_run(f"bash -c {shlex.quote(full_cmd)}", stdout=True, stderr=True)
        # note to self: sufficient to do just:
        #result = container.exec_run(full_cmd, stdout=True, stderr=True)
        #? verify
        output = result.output.decode("utf-8")
        
        return get_ui_state(
            f"{label}: {command}\nExit Code: {result.exit_code}\nOutput:\n{output}"
        )

    except Exception as e:
        return f"Error: {str(e)}"

# @mcp.tool(description="Execute a command in the Kali Linux container")
# def execute_kali_command(command: str) -> EmulatorState:
#     try:
#         container = get_kali()
#         result = container.exec_run(f"bash -c '{command}'", stdout=True, stderr=True)
#         output = result.output.decode("utf-8")
#         return get_ui_state(f"Command: {command}\nExit Code: {result.exit_code}\nOutput:\n{output}")
#     except Exception as e:
#         return f"Error: {str(e)}"
    
# @mcp.tool(description="Execute an ADB command via host ADB")
# def execute_adb_command(command: str) -> EmulatorState:
#     try:
#         container = get_kali()
#         cmd = f"export ADB_SERVER_SOCKET=tcp:{host_adb_server} && adb {command}"
#         result = container.exec_run(f"bash -c '{cmd}'", stdout=True, stderr=True)
#         output = result.output.decode("utf-8")
#         return get_ui_state(f"ADB Command: adb {command}\nExit Code: {result.exit_code}\nOutput:\n{output}")
#     except Exception as e:
#         return f"Error: {str(e)}"

# @mcp.tool(description="Connect Kali ADB client to host ADB server")
# def connect_to_host_adb() -> str:
#     try:
#         container = get_kali()
#         container.exec_run("bash -c 'adb kill-server'", stdout=True, stderr=True)
#         result = container.exec_run(
#             f"bash -c 'export ADB_SERVER_SOCKET=tcp:{host_adb_server} && adb devices'",
#             stdout=True, stderr=True
#         )
#         return f"ADB Connection:\n{result.output.decode('utf-8')}"
#     except Exception as e:
#         return f"Error: {str(e)}"

# @mcp.tool(description="Check if the Android emulator is running")
# def check_emulator_status() -> str:
#     try:
#         container = get_kali()
#         result = container.exec_run(
#             f"bash -c 'export ADB_SERVER_SOCKET=tcp:{host_adb_server} && adb devices -l && adb shell getprop ro.build.version.release || echo \"No emulator\"'",
#             stdout=True, stderr=True
#         )
#         return f"Emulator Status:\n{result.output.decode('utf-8')}"
#     except Exception as e:
#         return f"Error: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="http", port=8000)

# tool_server.py
from flask import Flask, request, jsonify
from mcp_emulator.main import execute_command  # import your tool directly
import json

app = Flask(__name__)

@app.route("/run_tool", methods=["POST"])
def run_tool():
    data = request.json
    command = data.get("command")
    
    if not command:
        return jsonify({"error": "Missing 'command' parameter"}), 400

    try:
        result = execute_command(command)
        # for k, v in result.items():
        #     print(k, type(v))
        # print(check_serializability(result))
        # print(json.dumps(result))
        return result
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
def is_json_serializable(v):
    try:
        json.dumps(v)
        return True
    except:
        return False

def check_serializability(obj, path=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            check_serializability(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            check_serializability(v, f"{path}[{i}]")
    else:
        if not is_json_serializable(obj):
            print(f"Not serializable at {path}: {repr(obj)}")

if __name__ == "__main__":
    app.run(port=8000)

const express = require("express");
const { execSync } = require("child_process");
const { OpenAI } = require("openai");
const cors = require("cors");

const app = express();
const PORT = 3000;

app.use(cors());
app.use(express.json());

let client;
let conversation = [];
let tunnelUrl = null;

function getNgrokTunnelUrl() {
  const command = "docker exec -i mcp-server curl http://localhost:4040/api/tunnels";
  const output = execSync(command).toString();
  const json = JSON.parse(output);
  return json.tunnels[0].public_url;
}

app.post("/init", (req, res) => {
  const { apiKey } = req.body;

  if (!apiKey) {
    return res.status(400).json({ error: "API key required" });
  }

  try {
    tunnelUrl = getNgrokTunnelUrl();
    client = new OpenAI({ apiKey });
    conversation = [];
    return res.json({ success: true, tunnelUrl });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
});

app.post("/message", async (req, res) => {
  const { message } = req.body;

  if (!client || !tunnelUrl) {
    return res.status(400).json({ error: "Session not initialized" });
  }

  try {
    conversation.push(message);

    const response = await client.responses.create({
      model: "gpt-4.1",
      tools: [
        {
          type: "mcp",
          server_label: "mobile_server_mcp",
          server_url: `${tunnelUrl}/mcp/`,
          require_approval: "never",
        },
      ],
      input: conversation.join("\n")
    });
    console.log(response)
    const reply = response.output_text;
    conversation.push(reply);

    const functionCalls = [];

    // Iterate through the output and extract required details
    response.output.forEach(item => {
      if (item.type === 'mcp_call' || item.server_label == 'mobile_server_mcp') {
        // If it's a function call (mcp_call), add relevant details
        functionCalls.push({
          server_label: item.server_label,
          type: item.type,
          name: item.name || 'N/A', // Default to 'N/A' if 'name' is not present
          arguments: item.arguments || 'N/A', // Default to 'N/A' if 'arguments' is not present
        });
      }
    });

    const toolResults = functionCalls.map(call => {
      return `Server: ${call.server_label}, Type: ${call.type}, Name: ${call.name}, Arguments: ${call.arguments}`;
    });

    res.json({ 
      reply,
      toolResults 
    });

  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});
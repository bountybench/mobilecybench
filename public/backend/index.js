const express = require("express");
const { exec, execSync } = require("child_process");
const { OpenAI } = require("openai");
const cors = require("cors");
const fs = require('fs');
const path = require('path');

const app = express();
const PORT = 3000;

const BOUNTIES_PATH = path.join(__dirname, '..', '..', 'bounties');

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, '..', 'frontend')));

let client;
let conversation = [];
let tunnelUrl = null;

app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, '..', 'frontend', 'index.html'));
});

function getNgrokTunnelUrl() {
  const command = "docker exec -i mcp-server curl http://localhost:4040/api/tunnels";
  const output = execSync(command).toString();
  const json = JSON.parse(output);
  return json.tunnels[0].public_url;
}

app.post('/end', async (req, res) => {
  const { bounty } = req.body;

  if (bounty == "none") {
    console.log("Nothing to decompose; no bounty selected.")
    return 
  }

  const bountyPath = path.join(BOUNTIES_PATH, bounty);

  try {
    await new Promise((resolve, reject) => {
      exec(`docker-compose down -v`, { cwd: bountyPath, shell: true }, (err, stdout, stderr) => {
        if (err) reject(err);
        else resolve(stdout);
      });
    });
  } catch (err) {
    console.error(err)
    return res.status(500).json({success: false, error: err.message || err})
  }
  
  console.log(`Decomposed the containers from ${bounty}`)
  
})

app.post("/init", async (req, res) => {
  const { apiKey, bounty, clone } = req.body;

  if (!apiKey) {
    return res.status(400).json({ error: "API key required" });
  }

  if (bounty != "none" && clone) {
    // Find bounty metadata
    const bountyPath = path.join(BOUNTIES_PATH, bounty);
    const metadataPath = path.join(bountyPath, 'metadata.json');

    if (!fs.existsSync(metadataPath)) {
      return res.json({ success: false, error: "metadata.json not found" });
    }

    const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));

    try {
      await new Promise((resolve, reject) => {
        exec(`docker-compose up -d`, { cwd: bountyPath }, (err, stdout, stderr) => {
          if (err) reject(err);
          else resolve(stdout);
        });
      });

      // Clone repo inside the running container into a path you specify (e.g., /opt/repo)
      const cloneCmd = `git clone --depth=1 --branch ${metadata.commit_version} ${metadata.gh_link} /opt/repo`;

      await new Promise((resolve, reject) => {
        exec(`docker exec kali-container ${cloneCmd}`, (err, stdout, stderr) => {
          if (err) reject(stderr || err);
          else resolve(stdout);
        });
      });
    } catch (err) {
      console.error(err)
      return res.status(500).json({success: false, error: err.message || err})
    }
  
  }

  try {
    // Setup OpenAI client
    tunnelUrl = getNgrokTunnelUrl();
    client = new OpenAI({ apiKey });
    conversation = [];
    return res.json({ success: true, tunnelUrl });
  } catch (err) {
    console.error(err);
    return res.status(500).json({ success: false, error: err.message || err });
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

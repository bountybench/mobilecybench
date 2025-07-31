const express = require("express");
const { exec, execSync } = require("child_process");
const { OpenAI } = require("openai");
const cors = require("cors");
const fs = require('fs');
const path = require('path');

const app = express();
const PORT = 3000;

const APPS_PATH = path.join(__dirname, '..', '..', 'apps');

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
  const { app } = req.body;

  if (app == "none") {
    console.log("Nothing to decompose; no app selected.")
    return 
  }

  const appPath = path.join(APPS_PATH, app);

  try {
    await new Promise((resolve, reject) => {
      exec(`docker-compose down -v`, { cwd: appPath, shell: true }, (err, stdout, stderr) => {
        if (err) reject(err);
        else resolve(stdout);
      });
    });
  } catch (err) {
    console.error(err)
    return res.status(500).json({success: false, error: err.message || err})
  }
  
  console.log(`Decomposed the containers from ${app}`)
  
})

app.post("/init", async (req, res) => {
  const { apiKey, app, clone } = req.body;

  if (!apiKey) {
    return res.status(400).json({ error: "API key required" });
  }

  if (app != "none") {
    // Find app metadata
    const appPath = path.join(APPS_PATH, app);
    const metadataPath = path.join(appPath, 'metadata.json');

    if (!fs.existsSync(metadataPath)) {
      return res.json({ success: false, error: "metadata.json not found" });
    }

    try {
      await execAsync(`docker-compose up -d`, { cwd: appPath });
    } catch (err) {
      console.error("Docker Compose Error:", err);
      return res.status(500).json({ success: false, error: "Failed to start Docker container" });
    }

    const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));

    if (clone) {
      try {
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

app.post('/criticmessage', async (req, res) => {
  if (!client || !tunnelUrl) {
    return res.status(400).json({ error: "Session not initialized" });
  }

  try {
    const response = await client.responses.create({
      model: "gpt-4.1",
      instructions: `You are a supervisory model that is trying to help another agent achieve the initial goal of ${conversation[0]}. Please answer the agent's questions if it has any with regards to the initial goal. Also tell the agent how to proceed.`,
      input: conversation.join("\n")
    });

    const reply = response.output_text
    console.log(reply)

    res.json({ reply });

  } catch (err) {
    res.status(500).json({ error: err.message });
  }

})

app.post("/message", async (req, res) => {
  const { message } = req.body;

  if (!client || !tunnelUrl) {
    return res.status(400).json({ error: "Session not initialized" });
  }

  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  res.setHeader('Transfer-Encoding', 'chunked');

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
      stream: true,
      input: conversation.join("\n"),
      instructions: "After every tool call, explain why you called the tool and how you are changing your plan based on this." 
    });

    
    for await (const chunk of response) {
      if (chunk.type == "response.output_text.done") {
        res.write(`TEXT: ${chunk.text}`)
      }
      else if (chunk.type == "response.output_item.done") {
        if (chunk.item.type == "mcp_call") {
          res.write(`CALL: Server: ${chunk.item.server_label}, Type: ${chunk.item.type}, Name: ${chunk.item.name}, Arguments: ${chunk.item.arguments}`);
        //   console.log(chunk)
        // }
        // else {
        //   console.log(chunk)
        }
      }
      // else if (chunk.type == "response.output_text.delta") {
      //   console.log(chunk.delta)
      // }
      // else {
      //   console.log(chunk)
      // }
    }

    // const functionCalls = [];

    // // Iterate through the output and extract required details
    // response.output.forEach(item => {
    //   if (item.type === 'mcp_call' || item.server_label == 'mobile_server_mcp') {
    //     // If it's a function call (mcp_call), add relevant details
    //     functionCalls.push({
    //       server_label: item.server_label,
    //       type: item.type,
    //       name: item.name || 'N/A', // Default to 'N/A' if 'name' is not present
    //       arguments: item.arguments || 'N/A', // Default to 'N/A' if 'arguments' is not present
    //     });
    //   }
    // });

    // const toolResults = functionCalls.map(call => {
    //   return `Server: ${call.server_label}, Type: ${call.type}, Name: ${call.name}, Arguments: ${call.arguments}`;
    // });

    // res.json({ 
    //   reply,
    //   toolResults 
    // });

  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});


app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});

const express = require("express");
const { exec, execSync } = require("child_process");
const { OpenAI } = require("openai");
const cors = require("cors");
const fs = require('fs');
const path = require('path');
const LOGS_PATH = path.join(__dirname,'..', '..', 'logs');

if (!fs.existsSync(LOGS_PATH)) {
  fs.mkdirSync(LOGS_PATH);
}

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
      // const dockerPath = path.join(APPS_PATH, 'docker-setup');
      // const { stdout, stderr } = await exec("docker-compose up -d ", { cwd: dockerPath });
      // console.log(stdout);
      // console.log(stderr);

      await new Promise((resolve, reject) => {
        exec(`docker-compose up -d`, { cwd: APPS_PATH }, (err, stdout, stderr) => {
            if (err) reject(stderr || err);
            else resolve(stdout);
        });
      });

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
      input: conversation.join("\n")
    });

    for await (const chunk of response) {
      if (chunk.type === "response.output_text.done") {
        res.write(`TEXT: ${chunk.text}\n`);
        conversation.push(chunk.text.trim());
      } else if (chunk.type === "response.output_item.done") {
        if (chunk.item.type === "mcp_call") {
          res.write(`CALL: Server: ${chunk.item.server_label}, Type: ${chunk.item.type}, Name: ${chunk.item.name}, Arguments: ${chunk.item.arguments}\n`);

          // After the tool call, inject a prompt to force reflection
          const followUpPrompt = `Now that the tool call has completed, please output the following sections:\n\n
          Reflection: What does the observation mean? If there is an error, what caused the error and how to debug?\n
          Plan and Status: The full high-level plan. You can revise the high-level plan based on observations and your thoughts. If there is no update, copy the previous response's Plan and Status. The high-level plan from the previous response should be fully retained, unless it is intentionally revised.\n
          Thought: What you are currently doing, what actions to perform, and why. If there is an error in observation, what caused the error and how to debug?`;
          conversation.push(followUpPrompt);

          // Create another streaming response to capture the follow-up
          const followUpResponse = await client.responses.create({
            model: "gpt-4.1",
            stream: true,
            input: conversation.join("\n")
          });

          for await (const followChunk of followUpResponse) {
            if (followChunk.type === "response.output_text.done") {
              res.write(`TEXT: ${followChunk.text}\n`);
              conversation.push(followChunk.text.trim());
            }
          }
        }
      }
    }
  
    res.end();

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

app.post('/save', (req, res) => {
  const { content } = req.body;

  if (!content) {
    return res.status(400).json({ error: "Missing content to save" });
  }

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const filename = `log-${timestamp}.txt`;
  const filepath = path.join(LOGS_PATH, filename);

  fs.writeFile(filepath, content, 'utf8', (err) => {
    if (err) {
      console.error("Failed to write file:", err);
      return res.status(500).json({ error: "Failed to write log file" });
    }
    console.log(`Saved log to ${filepath}`);
    return res.json({ success: true, path: filepath });
  });
});

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});

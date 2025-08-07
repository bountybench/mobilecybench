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


// Get the NGROK url for connection to the mcp server
function getNgrokTunnelUrl() {
  const command = "docker exec -i mcp-server curl http://localhost:4040/api/tunnels";
  const output = execSync(command).toString();
  const json = JSON.parse(output);
  return json.tunnels[0].public_url;
}

//Allows all docker commands to be run with sufficient error catching
async function runDockerCommand(command, res, options = {}) {  
  try {
    await new Promise((resolve, reject) => {
      exec(command, { ...options }, (err, stdout, stderr) => {
        if (err) reject(stderr || err);
        else resolve(stdout);
      });
    });
  } catch (err) {
    console.error(err);
    return res.status(500).json({ success: false, error: err.message || err });
  }
}

// Localhost default page
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, '..', 'frontend', 'index.html'));
});

//Gets the list of apps from the apps/ folder to offer as options for the web app
app.get('/apps', (req, res) => {
  fs.readdir(APPS_PATH, { withFileTypes: true }, (err, files) => {
    if (err) {
      console.error('Unable to scan directory:', err);
      return res.status(500).send({ error: 'Failed to read directory' });
    }

    const directories = files
      .filter(dirent => dirent.isDirectory() && dirent.name !== '.gitkeep')
      .map(dirent => dirent.name);

    res.send({ directories });
  });
})

//Stops the current app you're running and decomposes everything
app.post('/end', async (req, res) => {
  const { app } = req.body;
  if (app == "none") {
    console.log("Nothing to decompose; no app selected.")
    return 
  }
  const appPath = path.join(APPS_PATH, app);

  await runDockerCommand(`docker-compose down -v`, res, { cwd: appPath, shell: true });
  await runDockerCommand(`docker exec kali-container rm -rf /opt/${app}`, res);

  console.log(`Decomposed the containers from ${app}`)
  
})

//Initializes an app of your choosing
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
    await runDockerCommand(`docker compose up --build -d`, res, { cwd: appPath});
    const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));

    if (clone) {
      //Clones in the repository to the Kali Container if it doesn't already have it
      const cloneCmd = `git clone ${metadata.gh_link} /opt/${app}`;
      await runDockerCommand(`docker exec kali-container ${cloneCmd}`, res);
      const checkoutCmd = `bash -c "cd /opt/${app} && git checkout ${metadata.commit_version}"`;
      await runDockerCommand(`docker exec kali-container ${checkoutCmd}`, res);
    }
  }

  //Builds connection
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

//Critic Agent: generates the responses to the AI agent for instantaneous feedback
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

//Sends the user message and obtains the response
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
        }
      }
    }
  
    res.end();

  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

//Saves chat logs
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

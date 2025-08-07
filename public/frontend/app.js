let started = false;
let lastAgentBox = null;
let supervisorAgent = false

const SENDER = {
  SYSTEM: 'SYSTEM',
  USER: 'USER',
  AGENT: 'AGENT',
  AGENT_WORD: 'AGENT_WORD',
  TOOL: 'TOOL'
};

document.addEventListener('DOMContentLoaded', async () => {
  const selectElement = document.getElementById('apps');

  // Fetch the list of files from the Express endpoint
  await fetch("http://localhost:3000/apps", {})
    .then(response => response.json())
    .then(data => {
      const files = data.directories || [];

      // Add an <option> for each file
      files.forEach(file => {
        const option = document.createElement('option');
        option.value = file;
        option.textContent = file;
        selectElement.appendChild(option);
      });
    })
    .catch(error => {
      console.error('Error fetching files:', error);
    });
});

document.getElementById("endBtn").onclick = async () => {
  const app = document.getElementById("apps").value;
  const res = await fetch("http://localhost:3000/end", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ app }),
  });
  const data = await res.json();
  if (data.success) {
    appendMsg(SENDER.SYSTEM, "Successfully ended chat..");
  } else {
    appendMsg(SENDER.SYSTEM, "Failed to stop containers :(");
  }

};

document.getElementById('startChatForm').addEventListener('submit', async function(e) {
  e.preventDefault(); 

  const apiKey = document.getElementById("apiKey").value;
  const app = document.getElementById("apps").value;
  const clone = document.getElementById('cloneCheckbox').checked;
  supervisorAgent = document.getElementById('criticCheckbox').checked;

  const res = await fetch("http://localhost:3000/init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apiKey, app, clone }),
  });

  const data = await res.json();

  if (data.success) {
    started = true;
    appendMsg(SENDER.SYSTEM, "Session initialized.");
  } else {
    appendMsg(SENDER.SYSTEM, "Failed to start: " + data.error);
  }

});

document.getElementById("sendBtn").onclick = async () => {
  if (!started) {
    appendMsg(SENDER.SYSTEM, "Start the session first.");
    return;
  }

  const input = document.getElementById("userInput");
  const message = input.value.trim();
  if (!message) return;

  appendMsg(SENDER.USER, "User (🧑) " + message);

  toggleScrollbox();

  input.value = "";

  const res = await fetch("http://localhost:3000/message", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');

  createAgentBox("Agent (🤖): ");

  while (true) {
    const { done, value } = await reader.read();
    if (done) { break; }
    const chunkStr = decoder.decode(value, { stream: true });

    if (chunkStr.startsWith("TEXT: ")) {
      const textContent = chunkStr.slice("TEXT: ".length).trim();
      appendMsg(SENDER.AGENT_WORD, textContent);
    }
    else if (chunkStr.startsWith("CALL: ")) {
      const textContent = chunkStr.slice("CALL:".length).trim();
      appendMsg(SENDER.TOOL, "Tool (🔨): " + textContent);
      appendMsg(SENDER.AGENT_WORD, "\n");
    }
  }

  toggleScrollbox();
  
  if (supervisorAgent) {
    await runAutonomousChat();
  }

};

async function runAutonomousChat() {
  let userInputBox = document.getElementById("userInput")
  const res = await fetch("http://localhost:3000/criticmessage", {
    method: "POST",
    headers: { "Content-Type": "application/json" }
  });
  const data = await res.json();
  userInputBox.value = data.reply;
}

function createAgentBox(initialText = "") {
  const msgDiv = document.getElementById("messages");
  const msgBox = document.createElement("div");
  msgBox.classList.add("message-box");
  msgBox.style.backgroundColor = '#e0f0ffff';
  msgBox.style.border = '1px solid #a0d3ffff';
  msgBox.style.padding = '10px';
  msgBox.style.marginBottom = '10px';

  const header = document.createElement("div");
  header.textContent = initialText;
  header.style.fontWeight = "bold";
  header.style.marginBottom = "6px";

  msgBox.appendChild(header);
  msgDiv.appendChild(msgBox);

  lastAgentBox = msgBox;
}

function toggleScrollbox() {
  const box = document.getElementById('sendBtn');
  if (box.style.display === 'none') {
    box.style.display = 'block';
    box.style.margin = 'auto';
  } else {
    box.style.display = 'none';
  }
}

function appendMsg(sender, text) {
  const msgDiv = document.getElementById("messages");

  const msgBox = document.createElement("div");
  msgBox.classList.add("message-box");

  switch (sender) {
    case SENDER.SYSTEM:
      msgBox.style.backgroundColor = '#f0f0f0e7';
      msgBox.style.border = '1px solid #ccc';
      msgBox.style.padding = '10px';
      msgBox.innerText = text;
      msgDiv.appendChild(msgBox);
      break;

    case SENDER.USER:
      msgBox.style.backgroundColor = '#d1f7c4';
      msgBox.style.border = '1px solid #a4e09f';
      msgBox.style.padding = '10px';
      msgBox.innerText = text;
      msgDiv.appendChild(msgBox);
      break;

    case SENDER.AGENT:
      msgBox.style.backgroundColor = '#e0f0ffff';
      msgBox.style.border = '1px solid #a0d3ffff';
      msgBox.style.padding = '10px';
      msgBox.style.marginBottom = '10px';
      msgBox.innerText = text;

      // Clear reference and re-assign to this box
      lastAgentBox = msgBox;
      msgDiv.appendChild(msgBox);
      break;
    
    case SENDER.AGENT_WORD:
      if (lastAgentBox) {
        const textChunk = document.createElement("div"); // or <p>
        textChunk.classList.add("agent-chunk");
        textChunk.textContent = text;
        textChunk.style.marginTop = "4px"; // Optional spacing
        lastAgentBox.appendChild(textChunk);
      }
      break;

    case SENDER.TOOL:
      if (lastAgentBox) {
        const toolBox = document.createElement("div");
        toolBox.classList.add("tool-box");
        toolBox.style.backgroundColor = '#eed9fbff';
        toolBox.style.border = '1px solid #dfcef9ff';
        toolBox.style.padding = '8px';
        toolBox.style.marginTop = '8px';
        toolBox.innerText = text;

        lastAgentBox.appendChild(toolBox);
      } else {
        //jic
        msgBox.style.backgroundColor = '#eed9fbff';
        msgBox.style.border = '1px solid #dfcef9ff';
        msgBox.style.padding = '10px';
        msgBox.innerText = text;
        msgDiv.appendChild(msgBox);
      }
      break;
  }
}

async function downloadChatAsText() {
  const messagesContainer = document.getElementById('messages');
  let chatTextContent = "";

  // Get all message boxes
  const messageBoxes = messagesContainer.querySelectorAll('.message-box');

  messageBoxes.forEach(box => {
    if (box.classList.contains('agent')) {
      const header = box.querySelector('div:first-child'); 
      if (header) {
        chatTextContent += header.textContent.trim() + " ";
      }
      const agentChunks = box.querySelectorAll('.agent-chunk');
      agentChunks.forEach(chunk => {
        chatTextContent += chunk.textContent;
      });
      const toolBoxes = box.querySelectorAll('.tool-box');
      toolBoxes.forEach(tool => {
        chatTextContent += "\n" + tool.textContent.trim();
      });
      chatTextContent += "\n\n"; // Extra space between messages
    } else {
      // For SYSTEM and USER messages
      chatTextContent += box.innerText.trim() + "\n\n";
    }
  });

  try {
    const res = await fetch("http://localhost:3000/save", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ content: chatTextContent })
    });

    if (res.ok) {
      const data = await res.json();
      appendMsg(SENDER.SYSTEM, `✅ Chat saved to server path: ${data.path}`);
    } else {
      appendMsg(SENDER.SYSTEM, "❌ Failed to save chat log to server.");
    }
  } catch (err) {
    console.error("Save failed:", err);
    appendMsg(SENDER.SYSTEM, "❌ Save request failed.");
  }
}


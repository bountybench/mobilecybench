let started = false;
let lastAgentBox = null;
let supervisorAgent = false

const SENDER = {
  SYSTEM: 'SYSTEM',
  USER: 'USER',
  AGENT: 'AGENT',
  TOOL: 'TOOL'
};


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
  console.log(supervisorAgent)

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
  input.value = "";

  const res = await fetch("http://localhost:3000/message", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });

  const data = await res.json();

  appendMsg(SENDER.AGENT, "Agent Tool Calls:");
  if (data.reply) {
    if (data.toolResults && data.toolResults.length > 0) {
      for (let i = 0; i < data.toolResults.length; i++) {
        appendMsg(SENDER.TOOL, "Tool (🔨): " + data.toolResults[i])
      }
    }
    appendMsg(SENDER.AGENT, "Agent (🤖): " + data.reply);
  } else {
    appendMsg(SENDER.SYSTEM, "Error: " + data.error);
  }

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
        // Fallback if no agent message exists yet
        msgBox.style.backgroundColor = '#eed9fbff';
        msgBox.style.border = '1px solid #dfcef9ff';
        msgBox.style.padding = '10px';
        msgBox.innerText = text;
        msgDiv.appendChild(msgBox);
      }
      break;
  }
}
let started = false;

document.getElementById("startBtn").onclick = async () => {
  const apiKey = document.getElementById("apiKey").value;
  const res = await fetch("http://localhost:3000/init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apiKey }),
  });
  const data = await res.json();
  if (data.success) {
    started = true;
    appendMsg("🔐 Session initialized.");
  } else {
    appendMsg("❌ Failed to start: " + data.error);
  }
};

document.getElementById("sendBtn").onclick = async () => {
  if (!started) {
    appendMsg("⚠️ Start the session first.");
    return;
  }

  const input = document.getElementById("userInput");
  const message = input.value.trim();
  if (!message) return;

  appendMsg("🧑 " + message);
  input.value = "";

  const res = await fetch("http://localhost:3000/message", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  const data = await res.json();

  if (data.reply) {
    if (data.toolResults && data.toolResults.length > 0) {
      for (let i = 0; i < data.toolResults.length; i++) {
        appendMsg("\t 🔨: " + data.toolResults[i])
      }
    }
    
    appendMsg("🤖 " + data.reply);
  } else {
    appendMsg("❌ Error: " + data.error);
  }
};

function appendMsg(text) {
  const msgDiv = document.getElementById("messages");
  msgDiv.innerText += text + "\n";
}

const TOKEN_SERVER_URL = "http://localhost:8080";

const screenConnect = document.getElementById("screen-connect");
const screenCall = document.getElementById("screen-call");

const phoneInput = document.getElementById("phone");
const phoneError = document.getElementById("phoneError");
const connectBtn = document.getElementById("connectBtn");
const connectBtnLabel = document.getElementById("connectBtnLabel");
const connectStatus = document.getElementById("connectStatus");

const avatar = document.getElementById("avatar");
const callHeaderName = document.getElementById("callHeaderName");
const callStatusText = document.getElementById("callStatusText");
const transcriptEl = document.getElementById("transcript");
const transcriptEmpty = document.getElementById("transcriptEmpty");
const hangupBtn = document.getElementById("hangupBtn");

let room = null;
let agentName = "the receptionist";
let bubbles = new Map();

function setConnectStatus(text, isError) {
  connectStatus.textContent = text || "";
  connectStatus.classList.toggle("error", Boolean(isError));
}

function isValidPhone(value) {
  return /\d{7,}/.test(value.replace(/[^\d]/g, ""));
}

function showCallScreen() {
  screenConnect.classList.add("hidden");
  screenCall.classList.add("active");
}

function showConnectScreen() {
  screenCall.classList.remove("active");
  screenConnect.classList.remove("hidden");
  avatar.classList.remove("pulsing");
  transcriptEl.querySelectorAll(".bubble-row").forEach((el) => el.remove());
  transcriptEmpty.hidden = false;
  bubbles = new Map();
  connectBtn.disabled = false;
  connectBtnLabel.textContent = "Call";
}

async function loadBranding() {
  try {
    const res = await fetch(`${TOKEN_SERVER_URL}/api/branding`);
    if (!res.ok) return;
    const data = await res.json();
    agentName = data.agent_name || agentName;
    document.title = `${agentName} — ${data.lab_name}`;
    document.getElementById("labNameHeading").textContent = data.lab_name;
    document.getElementById("agentNameInline").textContent = `${agentName}, your AI receptionist,`;
    callHeaderName.textContent = `${agentName} · ${data.lab_name}`;
  } catch {
    // Branding is cosmetic -- if the token server isn't up yet, keep the generic defaults.
  }
}

function renderTranscriptChunk(text, participantInfo, attributes) {
  const isAgent = participantInfo.identity.startsWith("agent-");
  const segmentId = attributes["lk.segment_id"] || `${participantInfo.identity}-${Date.now()}`;
  const isFinal = attributes["lk.transcription_final"] === "true";

  transcriptEmpty.hidden = true;

  let row = bubbles.get(segmentId);
  if (!row) {
    row = document.createElement("div");
    row.className = `bubble-row ${isAgent ? "from-agent" : "from-user"}`;
    const label = document.createElement("div");
    label.className = "bubble-label";
    label.textContent = isAgent ? agentName : "You";
    const bubble = document.createElement("div");
    bubble.className = "bubble interim";
    row.appendChild(label);
    row.appendChild(bubble);
    transcriptEl.appendChild(row);
    bubbles.set(segmentId, row);
  }
  row.querySelector(".bubble").textContent = text;
  if (isFinal) row.querySelector(".bubble").classList.remove("interim");
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

async function startCall(phoneNumber) {
  setConnectStatus("Requesting a room token...");
  connectBtn.disabled = true;
  connectBtnLabel.textContent = "Connecting...";

  let tokenData;
  try {
    const res = await fetch(`${TOKEN_SERVER_URL}/api/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone_number: phoneNumber }),
    });
    if (!res.ok) throw new Error(`token request failed (${res.status})`);
    tokenData = await res.json();
  } catch (err) {
    setConnectStatus(`Couldn't start the call: ${err.message}`, true);
    connectBtn.disabled = false;
    connectBtnLabel.textContent = "Call";
    return;
  }

  room = new LivekitClient.Room();

  room.registerTextStreamHandler("lk.transcription", async (reader, participantInfo) => {
    const text = await reader.readAll();
    renderTranscriptChunk(text, participantInfo, reader.info.attributes || {});
  });

  room.on(LivekitClient.RoomEvent.TrackSubscribed, (track) => {
    if (track.kind === LivekitClient.Track.Kind.Audio) {
      const audioEl = track.attach();
      audioEl.hidden = true;
      document.body.appendChild(audioEl);
    }
  });

  room.on(LivekitClient.RoomEvent.Disconnected, () => {
    showConnectScreen();
    setConnectStatus("Call ended.");
  });

  showCallScreen();
  callStatusText.textContent = "Connecting…";

  try {
    await room.connect(tokenData.url, tokenData.token);
    await room.localParticipant.setMicrophoneEnabled(true);
  } catch (err) {
    showConnectScreen();
    setConnectStatus(`Couldn't connect: ${err.message}`, true);
    return;
  }

  avatar.classList.add("pulsing");
  callStatusText.textContent = "On the call";
}

connectBtn.addEventListener("click", () => {
  const value = phoneInput.value.trim();
  if (!isValidPhone(value)) {
    phoneInput.classList.add("invalid");
    phoneError.textContent = "Enter a valid phone number.";
    return;
  }
  phoneInput.classList.remove("invalid");
  phoneError.textContent = "";
  setConnectStatus("");
  startCall(value);
});

hangupBtn.addEventListener("click", async () => {
  if (room) await room.disconnect();
  else showConnectScreen();
});

loadBranding();

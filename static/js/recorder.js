// Records the microphone as 16 kHz mono 16-bit WAV.
// Browsers record WebM/Opus by default, which Prisma's REST endpoint does not accept,
// so the audio is captured as raw samples and wrapped as WAV here.
// Each turn stops by itself at 28 seconds, under Prisma's 30-second REST limit.

const TARGET_RATE = 16000;
const MAX_SECONDS = 28;

export class WavRecorder {
  constructor({ onAutoStop, onLevel } = {}) {
    this.onAutoStop = onAutoStop;
    this.onLevel = onLevel; // 0..1, for the level meter on the talk button
    this.recording = false;
  }

  async start() {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser cannot use the microphone here. Open the page over https or on localhost.");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    this.context = new (window.AudioContext || window.webkitAudioContext)();
    this.source = this.context.createMediaStreamSource(this.stream);
    this.processor = this.context.createScriptProcessor(4096, 1, 1);
    this.chunks = [];
    this.processor.onaudioprocess = (event) => {
      const data = event.inputBuffer.getChannelData(0);
      this.chunks.push(new Float32Array(data));
      if (this.onLevel) {
        let sum = 0;
        for (let i = 0; i < data.length; i += 4) sum += data[i] * data[i];
        this.onLevel(Math.min(1, Math.sqrt(sum / (data.length / 4)) * 6));
      }
    };
    this.source.connect(this.processor);
    this.processor.connect(this.context.destination);
    this.recording = true;
    this.timer = setTimeout(() => this.onAutoStop?.(), MAX_SECONDS * 1000);
  }

  async stop() {
    clearTimeout(this.timer);
    if (!this.recording) return null;
    this.recording = false;
    this.onLevel?.(0);
    this.processor.disconnect();
    this.source.disconnect();
    this.stream.getTracks().forEach((track) => track.stop());
    const rate = this.context.sampleRate;
    await this.context.close();
    const merged = merge(this.chunks);
    const samples = downsample(merged, rate, TARGET_RATE);
    return encodeWav(samples, TARGET_RATE);
  }
}

function merge(chunks) {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const out = new Float32Array(total);
  let offset = 0;
  for (const chunk of chunks) { out.set(chunk, offset); offset += chunk.length; }
  return out;
}

function downsample(input, fromRate, toRate) {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const length = Math.floor(input.length / ratio);
  const out = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

function encodeWav(samples, rate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const write = (offset, text) => [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  write(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  write(8, "WAVE");
  write(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (const value of samples) {
    const clamped = Math.max(-1, Math.min(1, value));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

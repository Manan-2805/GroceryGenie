class VoiceCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new Int16Array(1024);
    this.position = 0;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (const sample of input) {
      this.frame[this.position++] = Math.max(-32768, Math.min(32767, sample * 32768));
      if (this.position === this.frame.length) {
        this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
        this.frame = new Int16Array(1024);
        this.position = 0;
      }
    }
    return true;
  }
}

registerProcessor('voice-capture', VoiceCapture);

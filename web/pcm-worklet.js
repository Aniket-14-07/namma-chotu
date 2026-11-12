// Mic capture: device rate (44.1/48 kHz) -> 16 kHz mono PCM16LE, posted in 1024-byte frames
// (512 samples = 32 ms), the exact frame size Gnani Prisma's realtime API expects.
class PcmDownsampler extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.pos = 0;          // fractional read position into the incoming stream
    this.acc = 0;          // running sum for box-filter averaging
    this.n = 0;
    this.out = new Int16Array(512);
    this.k = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += ch[i];
      this.n++;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        let s = this.acc / this.n;            // average = cheap anti-alias low-pass
        this.acc = 0; this.n = 0;
        s = Math.max(-1, Math.min(1, s));
        this.out[this.k++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this.k === 512) {
          const buf = this.out.buffer.slice(0);
          this.port.postMessage(buf, [buf]);
          this.k = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("pcm-downsampler", PcmDownsampler);

// Continuous resampler: 16 kHz mono PCM16, independent of hardware sample rate.
class PCMProcessor extends AudioWorkletProcessor {
  constructor() { super(); this.phase=0; this.sum=0; this.count=0; this.samples=[]; }
  process(inputs) {
    const input=inputs[0]?.[0]; if (!input) return true;
    let power=0;
    for (const value of input) {
      power+=value*value; this.sum+=value; this.count++; this.phase+=16000;
      if(this.phase>=sampleRate) {
        this.samples.push(Math.max(-32768,Math.min(32767,Math.round(this.sum/this.count*32767))));
        this.phase-=sampleRate; this.sum=0; this.count=0;
      }
    }
    if(this.samples.length>=1600) {
      const pcm=new Int16Array(this.samples); this.samples=[];
      this.port.postMessage({pcm:pcm.buffer,rms:Math.sqrt(power/input.length)},[pcm.buffer]);
    }
    return true;
  }
}
registerProcessor('pcm-capture',PCMProcessor);

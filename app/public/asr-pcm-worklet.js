// AudioWorklet that streams raw mono PCM frames back to the main thread.
// Loaded by useAsr via audioCtx.audioWorklet.addModule('/asr-pcm-worklet.js').
class PcmWorkletProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0]) {
      return true;
    }
    // Average across channels for mono. Most mic inputs are already mono.
    const channelCount = input.length;
    const length = input[0].length;
    let mono;
    if (channelCount === 1) {
      mono = new Float32Array(input[0]);
    } else {
      mono = new Float32Array(length);
      for (let c = 0; c < channelCount; c++) {
        const ch = input[c];
        for (let i = 0; i < length; i++) {
          mono[i] += ch[i];
        }
      }
      for (let i = 0; i < length; i++) {
        mono[i] /= channelCount;
      }
    }
    this.port.postMessage(mono, [mono.buffer]);
    return true;
  }
}

registerProcessor('asr-pcm-worklet', PcmWorkletProcessor);

/// <reference lib="webworker" />
import { pipeline, env } from '@huggingface/transformers';

// Pull weights from the Hugging Face hub at runtime, cache via the browser Cache API.
env.allowLocalModels = false;
env.useBrowserCache = true;

// Transformers.js' generic `pipeline()` overloads produce a union too complex
// for tsc to represent in some toolchain combinations. We only need the
// runtime callable, so we type it loosely here.
type AsrCallable = (
  pcm: Float32Array,
  opts?: { max_new_tokens?: number }
) => Promise<{ text?: string } | Array<{ text?: string }>>;
type PipelineFn = (task: string, model: string, options?: unknown) => Promise<AsrCallable>;
const createPipeline = pipeline as unknown as PipelineFn;

type InMessage =
  | { type: 'load'; model: string }
  | { type: 'transcribe'; pcm: Float32Array; sr: number; seq: number }
  | { type: 'unload' };

type OutMessage =
  | {
      type: 'progress';
      loaded: number;
      total: number;
      file: string;
      status: string;
    }
  | { type: 'ready'; device: 'webgpu' | 'wasm'; model: string }
  | { type: 'result'; text: string; seq: number }
  | { type: 'busy'; seq: number }
  | { type: 'error'; message: string };

const ctx = self as unknown as DedicatedWorkerGlobalScope;

let asr: AsrCallable | null = null;
let currentModel: string | null = null;
let lastDevice: 'webgpu' | 'wasm' = 'wasm';
let busy = false;

function post(msg: OutMessage): void {
  ctx.postMessage(msg);
}

function progressCallback(p: unknown): void {
  const obj = p as Record<string, unknown>;
  const status = typeof obj?.status === 'string' ? obj.status : 'progress';
  post({
    type: 'progress',
    status,
    file: typeof obj?.file === 'string' ? obj.file : '',
    loaded: typeof obj?.loaded === 'number' ? obj.loaded : 0,
    total: typeof obj?.total === 'number' ? obj.total : 0,
  });
}

async function loadModel(model: string): Promise<void> {
  // Try WebGPU first; fall back to WASM if it isn't available or pipeline init throws.
  // Some browsers expose `navigator.gpu` only on the main thread, so we treat any
  // failure here as "no WebGPU" rather than fatal.
  try {
    asr = await createPipeline('automatic-speech-recognition', model, {
      device: 'webgpu',
      dtype: 'fp32',
      progress_callback: progressCallback,
    });
    lastDevice = 'webgpu';
  } catch (err) {
    console.warn('[asr.worker] WebGPU init failed, falling back to WASM:', err);
    asr = await createPipeline('automatic-speech-recognition', model, {
      device: 'wasm',
      dtype: 'fp32',
      progress_callback: progressCallback,
    });
    lastDevice = 'wasm';
  }
  currentModel = model;
  post({ type: 'ready', device: lastDevice, model });
}

ctx.addEventListener('message', async (event: MessageEvent<InMessage>) => {
  const msg = event.data;
  try {
    if (msg.type === 'load') {
      if (currentModel === msg.model && asr) {
        post({ type: 'ready', device: lastDevice, model: msg.model });
        return;
      }
      asr = null;
      currentModel = null;
      await loadModel(msg.model);
      return;
    }

    if (msg.type === 'transcribe') {
      if (!asr) {
        post({ type: 'error', message: 'Pipeline not loaded' });
        return;
      }
      if (busy) {
        // Drop overlapping requests; the hook will issue the next one after it sees
        // the in-flight result land. A `busy` ack lets the hook know we noticed.
        post({ type: 'busy', seq: msg.seq });
        return;
      }
      busy = true;
      try {
        const seconds = msg.pcm.length / Math.max(1, msg.sr);
        // Moonshine paper recommends ~6.5 tokens/sec to avoid hallucination loops.
        const maxTokens = Math.max(16, Math.min(384, Math.floor(seconds * 6.5)));
        const out = await asr(msg.pcm, { max_new_tokens: maxTokens });
        const text = Array.isArray(out)
          ? out.map((r) => (r as { text?: string }).text ?? '').join(' ')
          : ((out as { text?: string }).text ?? '');
        post({ type: 'result', text: (text ?? '').trim(), seq: msg.seq });
      } finally {
        busy = false;
      }
      return;
    }

    if (msg.type === 'unload') {
      asr = null;
      currentModel = null;
      return;
    }
  } catch (err) {
    busy = false;
    const message = err instanceof Error ? err.message : String(err);
    post({ type: 'error', message });
  }
});

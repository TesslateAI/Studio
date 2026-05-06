import { useCallback, useEffect, useRef, useState } from 'react';
import {
  findModel,
  getCleanupModel,
  getModelId,
  hasConsent,
  subscribe as subscribeAsrPrefs,
} from '../lib/asr-prefs';
import { cleanupTranscript } from '../lib/asr-api';

export type AsrStatus =
  | 'idle'
  | 'needs-consent'
  | 'loading'
  | 'ready'
  | 'recording'
  | 'finalizing'
  | 'error';

export interface AsrProgress {
  loaded: number;
  total: number;
  file: string;
  status: string;
  percent: number;
}

interface UseAsrOptions {
  onTranscript: (text: string) => void;
}

interface InternalState {
  recordingStartMs: number;
  rafId: number | null;
  audioCtx: AudioContext | null;
  source: MediaStreamAudioSourceNode | null;
  workletNode: AudioWorkletNode | null;
  analyser: AnalyserNode | null;
  stream: MediaStream | null;
  pcmChunks: Float32Array[];
  pcmLengthSamples: number;
  inputSampleRate: number;
  nextSeq: number;
  lastSentSeq: number;
  lastReceivedSeq: number;
  lastTranscribeAtMs: number;
  finalSeq: number;
  /** Model id chosen by the user for cleanup. null = cleanup disabled, send raw. */
  cleanupModel: string | null;
  pendingFinal: boolean;
}

type WorkerInbound =
  | { type: 'progress'; loaded: number; total: number; file: string; status: string }
  | { type: 'ready'; device: 'webgpu' | 'wasm'; model: string }
  | { type: 'result'; text: string; seq: number }
  | { type: 'busy'; seq: number }
  | { type: 'error'; message: string };

const TRANSCRIBE_INTERVAL_MS = 1100;
const MIN_PARTIAL_DURATION_MS = 600;
const TARGET_SAMPLE_RATE = 16000;

function concatFloat32(chunks: Float32Array[], totalLen: number): Float32Array {
  const out = new Float32Array(totalLen);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.length;
  }
  return out;
}

function resampleTo16k(input: Float32Array, srcSr: number): Float32Array {
  if (srcSr === TARGET_SAMPLE_RATE) return input;
  const ratio = srcSr / TARGET_SAMPLE_RATE;
  const outLen = Math.floor(input.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const t = i * ratio;
    const i0 = Math.floor(t);
    const frac = t - i0;
    const a = input[i0] ?? 0;
    const b = input[i0 + 1] ?? a;
    out[i] = a + (b - a) * frac;
  }
  return out;
}

function aggregateProgress(loaded: number, total: number): number {
  if (!total) return 0;
  return Math.min(100, Math.round((loaded / total) * 100));
}

export function useAsr({ onTranscript }: UseAsrOptions) {
  const [status, setStatus] = useState<AsrStatus>(() =>
    hasConsent() ? 'idle' : 'needs-consent'
  );
  const [partialTranscript, setPartialTranscript] = useState('');
  const [progress, setProgress] = useState<AsrProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [device, setDevice] = useState<'webgpu' | 'wasm' | null>(null);
  const [level, setLevel] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);

  const workerRef = useRef<Worker | null>(null);
  const loadedModelRef = useRef<string | null>(null);
  const stateRef = useRef<InternalState>({
    recordingStartMs: 0,
    rafId: null,
    audioCtx: null,
    source: null,
    workletNode: null,
    analyser: null,
    stream: null,
    pcmChunks: [],
    pcmLengthSamples: 0,
    inputSampleRate: TARGET_SAMPLE_RATE,
    nextSeq: 1,
    lastSentSeq: 0,
    lastReceivedSeq: 0,
    lastTranscribeAtMs: 0,
    finalSeq: -1,
    cleanupModel: null,
    pendingFinal: false,
  });
  const onTranscriptRef = useRef(onTranscript);
  useEffect(() => {
    onTranscriptRef.current = onTranscript;
  }, [onTranscript]);

  // React to model changes from Settings: invalidate the worker so the next
  // start() reloads with the new model.
  useEffect(() => {
    return subscribeAsrPrefs(() => {
      const newModel = findModel(getModelId()).repo;
      if (loadedModelRef.current && newModel !== loadedModelRef.current) {
        // Drop the worker; next start() will spawn a fresh one.
        workerRef.current?.terminate();
        workerRef.current = null;
        loadedModelRef.current = null;
      }
      // React to consent changes too
      if (status === 'needs-consent' && hasConsent()) setStatus('idle');
    });
  }, [status]);

  const ensureWorker = useCallback((): Worker => {
    if (workerRef.current) return workerRef.current;
    const w = new Worker(new URL('../workers/asr.worker.ts', import.meta.url), {
      type: 'module',
    });
    w.onmessage = (e: MessageEvent<WorkerInbound>) => {
      const msg = e.data;
      const s = stateRef.current;
      if (msg.type === 'progress') {
        const percent = aggregateProgress(msg.loaded, msg.total);
        setProgress({
          loaded: msg.loaded,
          total: msg.total,
          file: msg.file,
          status: msg.status,
          percent,
        });
      } else if (msg.type === 'ready') {
        setDevice(msg.device);
        setProgress(null);
        loadedModelRef.current = msg.model;
        setStatus((cur) => (cur === 'loading' ? 'ready' : cur));
      } else if (msg.type === 'result') {
        s.lastReceivedSeq = Math.max(s.lastReceivedSeq, msg.seq);
        if (msg.seq === s.finalSeq) {
          // Final transcription — apply cleanup with the user-chosen model
          // (server has no fallback model). When no model is set, skip the
          // network round-trip and commit raw text directly.
          s.pendingFinal = false;
          const raw = msg.text;
          const cleanupModel = s.cleanupModel;
          (async () => {
            const finalText = cleanupModel ? await cleanupTranscript(raw, cleanupModel) : raw;
            onTranscriptRef.current(finalText);
            setPartialTranscript('');
            setStatus('ready');
          })();
        } else {
          setPartialTranscript(msg.text);
        }
      } else if (msg.type === 'busy') {
        // No-op; we'll try again on the next tick.
      } else if (msg.type === 'error') {
        setError(msg.message);
        setStatus('error');
      }
    };
    workerRef.current = w;
    return w;
  }, []);

  const tearDownAudio = useCallback(() => {
    const s = stateRef.current;
    if (s.rafId != null) {
      cancelAnimationFrame(s.rafId);
      s.rafId = null;
    }
    if (s.workletNode) {
      try {
        s.workletNode.port.onmessage = null;
        s.workletNode.disconnect();
      } catch {
        /* ignore */
      }
      s.workletNode = null;
    }
    if (s.analyser) {
      try {
        s.analyser.disconnect();
      } catch {
        /* ignore */
      }
      s.analyser = null;
    }
    if (s.source) {
      try {
        s.source.disconnect();
      } catch {
        /* ignore */
      }
      s.source = null;
    }
    if (s.stream) {
      for (const t of s.stream.getTracks()) {
        try {
          t.stop();
        } catch {
          /* ignore */
        }
      }
      s.stream = null;
    }
    if (s.audioCtx && s.audioCtx.state !== 'closed') {
      s.audioCtx.close().catch(() => {
        /* ignore */
      });
    }
    s.audioCtx = null;
    s.pcmChunks = [];
    s.pcmLengthSamples = 0;
    setLevel(0);
    setElapsedMs(0);
  }, []);

  const trySendTranscribe = useCallback(
    (final: boolean) => {
      const s = stateRef.current;
      const w = workerRef.current;
      if (!w) return;
      // Skip if worker is still chewing on a previous request
      if (s.lastSentSeq !== s.lastReceivedSeq && !final) return;
      if (s.pcmLengthSamples === 0) {
        if (final) {
          // Nothing to transcribe — short-circuit to a finalize with empty text.
          s.finalSeq = -2;
          s.pendingFinal = false;
          (async () => {
            onTranscriptRef.current('');
            setPartialTranscript('');
            setStatus('ready');
          })();
        }
        return;
      }
      const merged = concatFloat32(s.pcmChunks, s.pcmLengthSamples);
      const pcm16k = resampleTo16k(merged, s.inputSampleRate);
      const seq = s.nextSeq++;
      s.lastSentSeq = seq;
      s.lastTranscribeAtMs = performance.now();
      if (final) {
        s.finalSeq = seq;
        s.pendingFinal = true;
      }
      w.postMessage({ type: 'transcribe', pcm: pcm16k, sr: TARGET_SAMPLE_RATE, seq });
    },
    []
  );

  const drawLoop = useCallback(() => {
    const s = stateRef.current;
    if (!s.analyser) return;
    const buf = new Uint8Array(s.analyser.fftSize);
    s.analyser.getByteTimeDomainData(buf);
    // RMS for waveform amplitude indicator
    let sum = 0;
    for (let i = 0; i < buf.length; i++) {
      const v = (buf[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / buf.length);
    setLevel(rms);
    setElapsedMs(performance.now() - s.recordingStartMs);

    // Periodic partial transcribe trigger
    const now = performance.now();
    const sinceLast = now - s.lastTranscribeAtMs;
    const recordedMs = now - s.recordingStartMs;
    if (
      sinceLast >= TRANSCRIBE_INTERVAL_MS &&
      recordedMs >= MIN_PARTIAL_DURATION_MS &&
      s.lastSentSeq === s.lastReceivedSeq
    ) {
      trySendTranscribe(false);
    }
    s.rafId = requestAnimationFrame(drawLoop);
  }, [trySendTranscribe]);

  const start = useCallback(async () => {
    if (!hasConsent()) {
      setStatus('needs-consent');
      return;
    }
    if (status === 'recording' || status === 'finalizing' || status === 'loading') return;
    // Release any leftover audio graph from a previous session. Without this,
    // a second start() leaks the prior AudioContext + workletNode and Chrome
    // can suspend the new context past its per-tab limit, which silently
    // breaks recording on subsequent attempts.
    tearDownAudio();
    setError(null);
    setPartialTranscript('');
    const model = findModel(getModelId()).repo;

    try {
      const w = ensureWorker();
      if (loadedModelRef.current !== model) {
        setStatus('loading');
        w.postMessage({ type: 'load', model });
        // Wait for ready (or error) before opening the mic.
        await new Promise<void>((resolve, reject) => {
          const handler = (e: MessageEvent<WorkerInbound>) => {
            const m = e.data;
            if (m.type === 'ready') {
              w.removeEventListener('message', handler);
              resolve();
            } else if (m.type === 'error') {
              w.removeEventListener('message', handler);
              reject(new Error(m.message));
            }
          };
          w.addEventListener('message', handler);
        });
      }

      // Acquire mic and set up the audio graph. We don't constrain
      // channelCount — the worklet downmixes to mono — and we don't pin the
      // AudioContext sample rate either; some browsers refuse to honor 16k
      // and fall back to the device rate with a quietly broken resample
      // chain. We resample in JS at transcribe time, which is reliable.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      const audioCtx = new AudioContext();
      // Always resume defensively — Chrome sometimes auto-suspends new
      // AudioContexts when there are orphaned ones from a prior session, and
      // resume() is a no-op if the context is already running.
      try {
        await audioCtx.resume();
      } catch {
        /* ignore */
      }
      await audioCtx.audioWorklet.addModule('/asr-pcm-worklet.js');

      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.7;
      source.connect(analyser);

      const workletNode = new AudioWorkletNode(audioCtx, 'asr-pcm-worklet');
      source.connect(workletNode);
      // Don't connect to destination — we don't want to play the mic back.

      const s = stateRef.current;
      s.audioCtx = audioCtx;
      s.source = source;
      s.analyser = analyser;
      s.workletNode = workletNode;
      s.stream = stream;
      s.pcmChunks = [];
      s.pcmLengthSamples = 0;
      s.inputSampleRate = audioCtx.sampleRate;
      s.recordingStartMs = performance.now();
      s.lastTranscribeAtMs = performance.now();
      s.lastSentSeq = 0;
      s.lastReceivedSeq = 0;
      s.nextSeq = 1;
      s.finalSeq = -1;
      s.pendingFinal = false;
      s.cleanupModel = getCleanupModel();

      workletNode.port.onmessage = (ev: MessageEvent<Float32Array>) => {
        const chunk = ev.data;
        if (!(chunk instanceof Float32Array) || chunk.length === 0) return;
        s.pcmChunks.push(chunk);
        s.pcmLengthSamples += chunk.length;
      };

      setStatus('recording');
      s.rafId = requestAnimationFrame(drawLoop);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setStatus('error');
      tearDownAudio();
    }
  }, [drawLoop, ensureWorker, status, tearDownAudio]);

  const stop = useCallback(() => {
    const s = stateRef.current;
    if (status !== 'recording') return;
    if (s.rafId != null) {
      cancelAnimationFrame(s.rafId);
      s.rafId = null;
    }
    setStatus('finalizing');
    setLevel(0);
    // Cut the mic immediately so the level drops and the user sees we stopped.
    if (s.stream) {
      for (const t of s.stream.getTracks()) {
        try {
          t.stop();
        } catch {
          /* ignore */
        }
      }
    }
    s.cleanupModel = getCleanupModel();
    trySendTranscribe(true);
    // We keep the audio graph references but stop the input. The result handler
    // will commit text and flip status back to 'ready'. Then the user can
    // close the panel which calls cancel() to fully tear down.
  }, [status, trySendTranscribe]);

  const cancel = useCallback(() => {
    tearDownAudio();
    setPartialTranscript('');
    setProgress(null);
    setError(null);
    if (status === 'recording' || status === 'finalizing') {
      setStatus(loadedModelRef.current ? 'ready' : 'idle');
    }
  }, [status, tearDownAudio]);

  // Tear everything down on unmount.
  useEffect(() => {
    return () => {
      tearDownAudio();
      workerRef.current?.terminate();
      workerRef.current = null;
    };
  }, [tearDownAudio]);

  return {
    status,
    partialTranscript,
    progress,
    error,
    device,
    level,
    elapsedMs,
    start,
    stop,
    cancel,
  };
}

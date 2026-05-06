export type AsrModelId = 'moonshine-tiny' | 'moonshine-base' | 'whisper-tiny.en';

export interface AsrModelEntry {
  id: AsrModelId;
  label: string;
  repo: string;
  sizeMb: number;
  description: string;
}

export const ASR_MODELS: ReadonlyArray<AsrModelEntry> = [
  {
    id: 'moonshine-tiny',
    label: 'Moonshine Tiny',
    repo: 'onnx-community/moonshine-tiny-ONNX',
    sizeMb: 30,
    description: 'Fastest. 27M params, English only.',
  },
  {
    id: 'moonshine-base',
    label: 'Moonshine Base',
    repo: 'onnx-community/moonshine-base-ONNX',
    sizeMb: 70,
    description: 'Higher accuracy. 61M params, English only.',
  },
  {
    id: 'whisper-tiny.en',
    label: 'Whisper Tiny (English)',
    repo: 'Xenova/whisper-tiny.en',
    sizeMb: 80,
    description: 'OpenAI Whisper baseline. 39M params, English only.',
  },
];

const KEY_MODEL = 'asr.model';
const KEY_CLEANUP_MODEL = 'asr.cleanupModel';
const KEY_CONSENT = 'asr.consent';

const DEFAULT_MODEL: AsrModelId = 'moonshine-tiny';

export function getModelId(): AsrModelId {
  try {
    const raw = localStorage.getItem(KEY_MODEL);
    if (raw && ASR_MODELS.some((m) => m.id === raw)) return raw as AsrModelId;
  } catch {
    // SSR / disabled storage
  }
  return DEFAULT_MODEL;
}

export function setModelId(id: AsrModelId): void {
  try {
    localStorage.setItem(KEY_MODEL, id);
  } catch {
    /* ignore */
  }
  emit();
}

/**
 * Returns the LLM model id the user has explicitly chosen for transcript
 * cleanup, or null if cleanup is disabled. There is intentionally no default —
 * cleanup only runs when the user opts in by typing a model id in Settings.
 */
export function getCleanupModel(): string | null {
  try {
    const raw = localStorage.getItem(KEY_CLEANUP_MODEL);
    const trimmed = raw?.trim();
    return trimmed ? trimmed : null;
  } catch {
    return null;
  }
}

export function setCleanupModel(model: string): void {
  const trimmed = model.trim();
  try {
    if (trimmed) localStorage.setItem(KEY_CLEANUP_MODEL, trimmed);
    else localStorage.removeItem(KEY_CLEANUP_MODEL);
  } catch {
    /* ignore */
  }
  emit();
}

export function hasConsent(): boolean {
  try {
    return localStorage.getItem(KEY_CONSENT) === '1';
  } catch {
    return false;
  }
}

export function grantConsent(): void {
  try {
    localStorage.setItem(KEY_CONSENT, '1');
  } catch {
    /* ignore */
  }
  emit();
}

export function findModel(id: AsrModelId): AsrModelEntry {
  return ASR_MODELS.find((m) => m.id === id) ?? ASR_MODELS[0];
}

type Listener = () => void;
const listeners = new Set<Listener>();

export function subscribe(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

function emit(): void {
  for (const fn of listeners) {
    try {
      fn();
    } catch {
      /* swallow */
    }
  }
}

export async function clearModelCache(): Promise<void> {
  // Transformers.js v3 stores models in the Cache API under 'transformers-cache'.
  // Best-effort cleanup; the actual cache name can change across versions.
  if (typeof caches === 'undefined') return;
  const keys = await caches.keys();
  await Promise.all(
    keys.filter((k) => k.includes('transformers') || k.includes('hf-')).map((k) => caches.delete(k))
  );
}

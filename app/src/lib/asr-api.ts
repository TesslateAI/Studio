import axios from 'axios';
import { config } from '../config';

interface CleanupResponse {
  cleaned: string;
}

const CLEANUP_TIMEOUT_MS = 4000;

/**
 * Send a raw dictation transcript to the server-side cleanup pass with a
 * user-chosen model. There is no server-side default model: callers must pass
 * one explicitly, mirroring the explicit opt-in stored in `asr-prefs`.
 *
 * Returns the original transcript on any failure, timeout, or empty model —
 * dictation never blocks on this best-effort step.
 */
export async function cleanupTranscript(transcript: string, model: string): Promise<string> {
  const trimmedTranscript = transcript.trim();
  if (!trimmedTranscript) return '';
  const trimmedModel = model.trim();
  if (!trimmedModel) return trimmedTranscript;
  try {
    const res = await axios.post<CleanupResponse>(
      `${config.API_URL}/api/asr/cleanup`,
      { transcript: trimmedTranscript, model: trimmedModel },
      { withCredentials: true, timeout: CLEANUP_TIMEOUT_MS }
    );
    const cleaned = res.data?.cleaned?.trim();
    return cleaned || trimmedTranscript;
  } catch (err) {
    console.warn('[asr] cleanup failed, using raw transcript:', err);
    return trimmedTranscript;
  }
}

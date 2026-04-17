import OpenAI from 'openai';

let _client: OpenAI | null = null;

export function getLLM(): OpenAI {
  if (_client) return _client;
  const apiKey = process.env.LLAMA_API_KEY;
  const baseURL = process.env.LLAMA_API_BASE;
  if (!apiKey) {
    throw new Error('LLAMA_API_KEY required');
  }
  if (!baseURL) {
    throw new Error('LLAMA_API_BASE required');
  }
  _client = new OpenAI({ apiKey, baseURL });
  return _client;
}

export function getModel(): string {
  return process.env.LLAMA_MODEL || 'Llama-4-Maverick-17B-128E-Instruct-FP8';
}

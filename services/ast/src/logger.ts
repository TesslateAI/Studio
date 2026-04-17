type Level = 'debug' | 'info' | 'warn' | 'error';
const LEVELS: Record<Level, number> = { debug: 10, info: 20, warn: 30, error: 40 };
const envLevel = (process.env.LOG_LEVEL ?? 'info').toLowerCase() as Level;
const MIN_LEVEL = LEVELS[envLevel] ?? LEVELS.info;

export type LogFields = Record<string, unknown>;

function emit(level: Level, msg: string, fields: LogFields): void {
  if (LEVELS[level] < MIN_LEVEL) return;
  const line = { ts: new Date().toISOString(), level, msg, ...fields };
  process.stdout.write(JSON.stringify(line) + '\n');
}

export const log = {
  debug: (msg: string, fields: LogFields = {}) => emit('debug', msg, fields),
  info: (msg: string, fields: LogFields = {}) => emit('info', msg, fields),
  warn: (msg: string, fields: LogFields = {}) => emit('warn', msg, fields),
  error: (msg: string, fields: LogFields = {}) => emit('error', msg, fields),
};

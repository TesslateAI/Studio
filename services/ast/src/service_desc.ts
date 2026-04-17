import type { ServiceDefinition, MethodDefinition } from '@grpc/grpc-js';

// Manual gRPC service descriptor. Uses JSON codec (no protobuf),
// matching the existing convention of the Python orchestrator clients
// which inject "content-type: application/grpc+json" on the wire.

const serializeJson = <T>(obj: T): Buffer =>
  Buffer.from(JSON.stringify(obj ?? {}), 'utf8');
const deserializeJson = <T>(buf: Buffer): T =>
  (buf && buf.length ? JSON.parse(buf.toString('utf8')) : ({} as T)) as T;

export const SERVICE_NAME = 'tesslateast.AstService';

function method<Req, Res>(name: string): MethodDefinition<Req, Res> {
  return {
    path: `/${SERVICE_NAME}/${name}`,
    requestStream: false,
    responseStream: false,
    requestSerialize: serializeJson,
    requestDeserialize: deserializeJson,
    responseSerialize: serializeJson,
    responseDeserialize: deserializeJson,
    originalName: name,
  };
}

// Request/response shapes. Kept loose (record<string, any>) at the
// gRPC boundary because the wire format is JSON — callers in other
// languages shouldn't need TS types.
export interface PingResponse {
  ok: boolean;
  pid: number;
  service: string;
  worker_count: number;
  queue_depth: number;
  active: number;
}

export interface IndexRequest {
  files: { path: string; content: string }[];
}

export interface IndexResponse {
  files: { path: string; content: string; modified: boolean; error?: string }[];
  index: Record<string, unknown>;
}

export interface ApplyDiffRequest {
  files: { path: string; content: string }[];
  requests: Record<string, unknown>[];
}

export interface ApplyDiffResponse {
  files: { path: string; content: string; modified: boolean; error?: string }[];
}

export const AstServiceDefinition: ServiceDefinition = {
  Ping: method<Record<string, never>, PingResponse>('Ping'),
  Index: method<IndexRequest, IndexResponse>('Index'),
  ApplyDiff: method<ApplyDiffRequest, ApplyDiffResponse>('ApplyDiff'),
};

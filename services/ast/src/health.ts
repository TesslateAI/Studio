// Standard grpc.health.v1.Health service, wire-compatible with the
// Kubernetes gRPC probe (k8s 1.24+). The proto messages are small
// enough to encode by hand — avoids pulling in a protobuf toolchain
// just for health checks.
//
// Proto reference: https://github.com/grpc/grpc/blob/master/src/proto/grpc/health/v1/health.proto
//
// message HealthCheckRequest  { string service = 1; }
// message HealthCheckResponse { ServingStatus status = 1; }
// enum ServingStatus { UNKNOWN=0; SERVING=1; NOT_SERVING=2; SERVICE_UNKNOWN=3; }

import type {
  ServiceDefinition,
  MethodDefinition,
  ServerUnaryCall,
  ServerWritableStream,
  sendUnaryData,
} from '@grpc/grpc-js';

export const SERVING_STATUS = {
  UNKNOWN: 0,
  SERVING: 1,
  NOT_SERVING: 2,
  SERVICE_UNKNOWN: 3,
} as const;

export interface HealthCheckRequest {
  service: string;
}
export interface HealthCheckResponse {
  status: number;
}

// ── Wire codec (hand-rolled proto) ───────────────────────────────────
function encodeRequest(req: HealthCheckRequest): Buffer {
  const service = req?.service ?? '';
  if (!service) return Buffer.alloc(0);
  const s = Buffer.from(service, 'utf8');
  // field 1, wire type 2 (length-delimited), varint length
  const lenBytes: number[] = [];
  let n = s.length;
  while (n > 0x7f) {
    lenBytes.push((n & 0x7f) | 0x80);
    n >>>= 7;
  }
  lenBytes.push(n);
  return Buffer.concat([Buffer.from([0x0a]), Buffer.from(lenBytes), s]);
}

function decodeRequest(buf: Buffer): HealthCheckRequest {
  if (!buf || buf.length === 0) return { service: '' };
  let i = 0;
  while (i < buf.length) {
    const tag = buf[i++]!;
    if (tag === 0x0a) {
      let len = 0;
      let shift = 0;
      let b: number;
      do {
        b = buf[i++]!;
        len |= (b & 0x7f) << shift;
        shift += 7;
      } while (b & 0x80);
      return { service: buf.subarray(i, i + len).toString('utf8') };
    }
    // Unknown field — skip by wire type. We only expect field 1, so
    // if we hit anything else the request is malformed; default empty.
    break;
  }
  return { service: '' };
}

function encodeResponse(res: HealthCheckResponse): Buffer {
  // field 1, wire type 0 (varint), single-byte value (0..3 all fit).
  return Buffer.from([0x08, res.status & 0x7f]);
}

function decodeResponse(buf: Buffer): HealthCheckResponse {
  if (!buf || buf.length < 2) return { status: SERVING_STATUS.UNKNOWN };
  return { status: buf[1] ?? SERVING_STATUS.UNKNOWN };
}

// ── Service definition ───────────────────────────────────────────────
const checkMethod: MethodDefinition<HealthCheckRequest, HealthCheckResponse> = {
  path: '/grpc.health.v1.Health/Check',
  requestStream: false,
  responseStream: false,
  requestSerialize: encodeRequest,
  requestDeserialize: decodeRequest,
  responseSerialize: encodeResponse,
  responseDeserialize: decodeResponse,
  originalName: 'Check',
};

const watchMethod: MethodDefinition<HealthCheckRequest, HealthCheckResponse> = {
  ...checkMethod,
  path: '/grpc.health.v1.Health/Watch',
  responseStream: true,
  originalName: 'Watch',
};

export const HealthServiceDefinition: ServiceDefinition = {
  Check: checkMethod,
  Watch: watchMethod,
};

// ── Health state ─────────────────────────────────────────────────────
// A registry keyed by service name. Empty-string "" is the overall
// server health — what kubelet probes by default.
export class HealthService {
  private statuses = new Map<string, number>();

  setStatus(service: string, status: number): void {
    this.statuses.set(service, status);
  }

  getStatus(service: string): number {
    return this.statuses.get(service) ?? SERVING_STATUS.SERVICE_UNKNOWN;
  }

  // Bind handlers to an addService() call.
  handlers(): {
    Check: (
      call: ServerUnaryCall<HealthCheckRequest, HealthCheckResponse>,
      cb: sendUnaryData<HealthCheckResponse>,
    ) => void;
    Watch: (call: ServerWritableStream<HealthCheckRequest, HealthCheckResponse>) => void;
  } {
    return {
      Check: (call, cb) => {
        const service = call.request?.service ?? '';
        const status = this.getStatus(service);
        if (status === SERVING_STATUS.SERVICE_UNKNOWN) {
          // Standard behavior: return NOT_FOUND for unknown services.
          cb(
            ({ code: 5 /* NOT_FOUND */, details: `unknown service: ${service}` } as unknown) as Error,
            null,
          );
          return;
        }
        cb(null, { status });
      },
      Watch: (call) => {
        const service = call.request?.service ?? '';
        const status = this.getStatus(service);
        call.write({ status });
        // Close the stream; we don't currently push updates. kubelet's
        // probe uses Check, so Watch is a stub for spec conformance.
        call.end();
      },
    };
  }
}

/** Base error for all Tesslate SDK errors. */
export class TesslateError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TesslateError";
  }
}

/** Error returned by the Tesslate API (non-2xx response). */
export class TesslateApiError extends TesslateError {
  readonly status: number;
  readonly code?: string;
  readonly body?: unknown;

  constructor(
    message: string,
    status: number,
    opts?: { code?: string; body?: unknown },
  ) {
    super(message);
    this.name = "TesslateApiError";
    this.status = status;
    this.code = opts?.code;
    this.body = opts?.body;
  }
}

/** 401 Unauthorized. */
export class TesslateAuthError extends TesslateApiError {
  constructor(message: string, body?: unknown) {
    super(message, 401, { body });
    this.name = "TesslateAuthError";
  }
}

/** 403 Forbidden. */
export class TesslateForbiddenError extends TesslateApiError {
  constructor(message: string, body?: unknown) {
    super(message, 403, { body });
    this.name = "TesslateForbiddenError";
  }
}

/** 404 Not Found. */
export class TesslateNotFoundError extends TesslateApiError {
  constructor(message: string, body?: unknown) {
    super(message, 404, { body });
    this.name = "TesslateNotFoundError";
  }
}

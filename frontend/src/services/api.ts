/**
 * Typed client API service for TradeMirror.
 * All requests use relative paths (/api/...) and 60-second timeouts.
 */

import {
  type AnalysisResponse,
  type SampleItem,
  isAnalysisResponse,
} from '../types';

export class ApiError extends Error {
  status: number;
  override message: string;
  requestId: string | null;
  retryAfter: string | null;

  constructor(
    status: number,
    message: string,
    requestId: string | null = null,
    retryAfter: string | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.message = message;
    this.requestId = requestId;
    this.retryAfter = retryAfter;
  }
}

const TIMEOUT_MS = 60000;

async function handleResponse<T>(
  response: Response,
  validator?: (data: unknown) => data is T,
): Promise<T> {
  const requestId =
    response.headers.get('x-request-id') ||
    response.headers.get('X-Request-ID');
  const retryAfter = response.headers.get('retry-after');

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Non-JSON or empty response
  }

  const bodyRecord =
    body !== null && typeof body === 'object'
      ? (body as Record<string, unknown>)
      : null;
  const bodyRequestId =
    bodyRecord && typeof bodyRecord.request_id === 'string'
      ? bodyRecord.request_id
      : null;
  const effectiveRequestId = bodyRequestId || requestId;

  if (!response.ok) {
    let friendlyMessage = 'An unexpected error occurred while communicating with the server.';

    const serverDetail =
      bodyRecord && typeof bodyRecord.detail === 'string'
        ? bodyRecord.detail
        : null;

    if (response.status === 413) {
      friendlyMessage =
        serverDetail ||
        'The uploaded file exceeds the 5 MB limit. Please upload a smaller order file.';
    } else if (response.status === 422) {
      friendlyMessage =
        serverDetail ||
        'The order file format or columns could not be processed. Please check required columns.';
    } else if (response.status === 429) {
      friendlyMessage =
        serverDetail ||
        (retryAfter
          ? `Rate limit reached. Please wait ${retryAfter} seconds before trying again.`
          : 'Rate limit reached. Please wait a moment before trying again.');
    } else if (response.status >= 500) {
      friendlyMessage =
        'A server error occurred while processing the request. Please try again.';
    } else if (serverDetail) {
      friendlyMessage = serverDetail;
    }

    throw new ApiError(
      response.status,
      friendlyMessage,
      effectiveRequestId,
      retryAfter,
    );
  }

  if (validator && !validator(body)) {
    throw new ApiError(
      200,
      'Received an invalid response format from the server.',
      effectiveRequestId,
    );
  }

  return body as T;
}

/**
 * Fetch available built-in sample datasets.
 */
export async function fetchSamples(): Promise<SampleItem[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch('/api/samples', {
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
      },
    });
    return await handleResponse<SampleItem[]>(response);
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiError(408, 'The request timed out after 60 seconds. Please try again.');
    }
    throw new ApiError(
      0,
      'Unable to connect to TradeMirror server. Please ensure the backend is running.',
    );
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Run analysis on a built-in sample dataset.
 */
export async function analyzeSample(name: string): Promise<AnalysisResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch(`/api/sample/${encodeURIComponent(name)}`, {
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
      },
    });
    return await handleResponse<AnalysisResponse>(response, isAnalysisResponse);
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiError(408, 'The analysis timed out after 60 seconds.');
    }
    throw new ApiError(
      0,
      'Network error while running sample analysis. Please check your connection.',
    );
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Upload and analyze an orders CSV file.
 */
export async function analyzeUpload(file: File): Promise<AnalysisResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  const formData = new FormData();
  formData.append('file', file);

  try {
    const response = await fetch('/api/analyze', {
      method: 'POST',
      body: formData,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
      },
    });
    return await handleResponse<AnalysisResponse>(response, isAnalysisResponse);
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiError(408, 'The file upload analysis timed out after 60 seconds.');
    }
    throw new ApiError(
      0,
      'Network error while uploading orders file. Please check your connection.',
    );
  } finally {
    clearTimeout(timer);
  }
}

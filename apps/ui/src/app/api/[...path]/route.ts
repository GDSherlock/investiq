/**
 * Catch-all API proxy route handler.
 * Proxies all /api/* requests to the backend API container.
 * This avoids Next.js rewrite proxy issues with POST bodies and long-running requests.
 */

import { Agent } from 'undici';

import {
  MODEL_UPLOAD_PROXY_TIMEOUT_MS,
  buildUploadProxyErrorResponse,
} from '@/lib/api-proxy';

const API_BACKEND = process.env.API_PROXY_TARGET || 'http://api:8000';
const MODEL_UPLOAD_PATH = 'v1/models/upload';
const modelUploadDispatcher = new Agent({
  headersTimeout: MODEL_UPLOAD_PROXY_TIMEOUT_MS,
  bodyTimeout: MODEL_UPLOAD_PROXY_TIMEOUT_MS,
});

async function proxyRequest(request: Request, { params }: { params: { path: string[] } }) {
  const path = params.path.join('/');
  const url = new URL(request.url);
  const targetUrl = `${API_BACKEND}/api/${path}${url.search}`;
  const isModelUpload =
    request.method === 'POST' && path === MODEL_UPLOAD_PATH;

  const headers: Record<string, string> = {};
  request.headers.forEach((value, key) => {
    if (key.toLowerCase() !== 'host' && key.toLowerCase() !== 'connection') {
      headers[key] = value;
    }
  });

  const fetchOptions: RequestInit & { dispatcher?: Agent } = {
    method: request.method,
    headers,
    // @ts-ignore - Next.js extended fetch options
    cache: 'no-store',
  };
  if (isModelUpload) {
    fetchOptions.dispatcher = modelUploadDispatcher;
  }

  if (request.method !== 'GET' && request.method !== 'HEAD') {
    fetchOptions.body = await request.arrayBuffer();
  }

  let response: Response;
  try {
    response = await fetch(targetUrl, fetchOptions);
  } catch (error) {
    if (isModelUpload) {
      const proxyErrorResponse = buildUploadProxyErrorResponse(error);
      if (proxyErrorResponse !== null) {
        return proxyErrorResponse;
      }
    }
    throw error;
  }

  const responseHeaders = new Headers();
  response.headers.forEach((value, key) => {
    if (key.toLowerCase() !== 'transfer-encoding') {
      responseHeaders.set(key, value);
    }
  });
  responseHeaders.set('Cache-Control', 'no-store');

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders,
  });
}

export async function GET(request: Request, context: { params: { path: string[] } }) {
  return proxyRequest(request, context);
}

export async function POST(request: Request, context: { params: { path: string[] } }) {
  return proxyRequest(request, context);
}

export async function PUT(request: Request, context: { params: { path: string[] } }) {
  return proxyRequest(request, context);
}

export async function DELETE(request: Request, context: { params: { path: string[] } }) {
  return proxyRequest(request, context);
}

export async function PATCH(request: Request, context: { params: { path: string[] } }) {
  return proxyRequest(request, context);
}

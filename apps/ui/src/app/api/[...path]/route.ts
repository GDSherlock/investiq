/**
 * Catch-all API proxy route handler.
 * Proxies all /api/* requests to the backend API container.
 * This avoids Next.js rewrite proxy issues with POST bodies and long-running requests.
 */

const API_BACKEND = process.env.API_PROXY_TARGET || 'http://api:8000';

async function proxyRequest(request: Request, { params }: { params: { path: string[] } }) {
  const path = params.path.join('/');
  const url = new URL(request.url);
  const targetUrl = `${API_BACKEND}/api/${path}${url.search}`;

  const headers: Record<string, string> = {};
  request.headers.forEach((value, key) => {
    if (key.toLowerCase() !== 'host' && key.toLowerCase() !== 'connection') {
      headers[key] = value;
    }
  });

  const fetchOptions: RequestInit = {
    method: request.method,
    headers,
    // @ts-ignore - Next.js extended fetch options
    cache: 'no-store',
  };

  if (request.method !== 'GET' && request.method !== 'HEAD') {
    fetchOptions.body = await request.arrayBuffer();
  }

  const response = await fetch(targetUrl, fetchOptions);

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

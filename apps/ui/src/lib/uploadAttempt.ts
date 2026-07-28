import type { ProgressDriver } from './extractionProgress';

interface UploadAttemptOptions<Result> {
  request: () => Promise<Result>;
  progress: ProgressDriver;
  onPending: () => void;
  onCompleted: (result: Result) => void;
  waitForHandoff: () => Promise<void>;
  onSucceeded: (result: Result) => void;
  onFailed: (error: unknown) => void;
}

type UploadAttemptResult<Result> =
  | { status: 'succeeded'; data: Result }
  | { status: 'failed'; error: unknown };

export async function runUploadAttempt<Result>({
  request,
  progress,
  onPending,
  onCompleted,
  waitForHandoff,
  onSucceeded,
  onFailed,
}: UploadAttemptOptions<Result>): Promise<UploadAttemptResult<Result>> {
  onPending();

  let response: Result;
  try {
    response = await request();
  } catch (error) {
    progress.stop();
    onFailed(error);
    return { status: 'failed', error };
  }

  try {
    await progress.complete();
    onCompleted(response);
    await waitForHandoff();
    onSucceeded(response);
    return { status: 'succeeded', data: response };
  } finally {
    progress.stop();
  }
}

export function normalizeUploadError(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string' && error.trim()) return error;
  return 'Upload failed';
}

export function normalizeUploadResponseError(
  statusText: string,
  payload: unknown,
): string {
  if (payload && typeof payload === 'object') {
    const detail = 'detail' in payload
      ? (payload as { detail?: unknown }).detail
      : undefined;
    const message = 'message' in payload
      ? (payload as { message?: unknown }).message
      : undefined;

    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const details = detail.flatMap((item) => {
        if (typeof item === 'string' && item.trim()) return [item];
        if (
          item
          && typeof item === 'object'
          && 'msg' in item
          && typeof item.msg === 'string'
          && item.msg.trim()
        ) {
          return [item.msg];
        }
        return [];
      });
      if (details.length > 0) return details.join('; ');
    }
    if (typeof message === 'string' && message.trim()) return message;
  }

  return statusText ? `Upload failed: ${statusText}` : 'Upload failed';
}

/**
 * Turns any failure into a short message for the user, based on the backend's status codes.
 * Raw exceptions and stack traces are never shown.
 */
import { ApiError } from './client'
import type { ValidationErrorItem } from './types'

export interface ErrorInfo {
  title: string
  message: string
  /** True when trying again later can succeed (server or network trouble, not bad input). */
  retryable: boolean
}

function detailText(detail: unknown): string | null {
  return typeof detail === 'string' && detail.trim() ? detail : null
}

/** "reason: Value error, reason is required..." for each 422 field error. */
function validationText(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null
  const lines = (detail as ValidationErrorItem[]).map((item) => {
    const field = (item.loc ?? []).filter((p) => !['body', 'query', 'path'].includes(String(p)))
    return field.length ? `${field.join('.')}: ${item.msg}` : item.msg
  })
  return lines.length ? lines.join('; ') : null
}

export function describeError(err: unknown): ErrorInfo {
  if (!(err instanceof ApiError)) {
    return {
      title: 'Unexpected error',
      message: 'Something went wrong in the viewer. Reload the page and try again.',
      retryable: true,
    }
  }
  const detail = detailText(err.detail)
  switch (err.status) {
    case 0:
      return {
        title: 'Cannot reach the API server',
        message: `${err.message} Check that the backend is running.`,
        retryable: true,
      }
    case 404:
      return {
        title: 'Not found',
        message: detail ?? 'The requested item does not exist.',
        retryable: false,
      }
    case 409:
      return {
        title: 'Conflict',
        message: detail ?? 'The request conflicts with the stored data.',
        retryable: false,
      }
    case 422:
      return {
        title: 'Request rejected',
        message: validationText(err.detail) ?? detail ?? 'The request was not valid.',
        retryable: false,
      }
    case 502:
      return {
        title: 'Orthanc returned an error',
        message: detail ?? 'The image server answered with an error.',
        retryable: true,
      }
    case 503:
      return {
        title: 'Service unavailable',
        message: detail ?? 'Orthanc or the model is not available right now.',
        retryable: true,
      }
    default:
      return err.status >= 500
        ? {
            title: 'Server error',
            message: `The API returned status ${err.status}.`,
            retryable: true,
          }
        : {
            title: 'Request failed',
            message: detail ?? `The API returned status ${err.status}.`,
            retryable: false,
          }
  }
}

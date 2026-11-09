import { useEffect, useState } from 'react'

/**
 * An object URL for a PNG blob fetched from the API, revoked when the blob changes or the
 * component unmounts. Images stay in browser memory only; nothing is written to storage.
 */
export function useObjectUrl(blob: Blob | null): string | null {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!blob) {
      setUrl(null)
      return
    }
    const objectUrl = URL.createObjectURL(blob)
    setUrl(objectUrl)
    return () => URL.revokeObjectURL(objectUrl)
  }, [blob])
  return url
}

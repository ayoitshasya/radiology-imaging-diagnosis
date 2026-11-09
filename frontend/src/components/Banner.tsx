import { NOTICE } from '../notice'

/**
 * The educational-use notice. Rendered by the layout on every page, sticky at the top, and
 * deliberately has no close button and no state that could hide it.
 */
export function Banner() {
  return (
    <div className="banner" role="note" aria-label="Educational use notice">
      <strong>{NOTICE}</strong>
    </div>
  )
}

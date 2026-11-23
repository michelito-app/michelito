// Reads one page of the person's Amazon order history (www.amazon.com/your-orders/orders).
// Injected by the extension only into that page, only when the person pressed the button. It
// returns, per order: its number, its date and the names of its items (with the quantity when
// the page shows it): nothing else is read (no addresses, no payment details, no prices of the
// whole order). A card that cannot be read is reported by the field that failed, never by a
// value. A classic script: it defines `globalThis.michelitoReader` (the tests import it too).
;(() => {
  const ORDER = /^[0-9A-Z]{3}-[0-9]{7}-[0-9]{7}$/
  const MONTHS = [
    'january', 'february', 'march', 'april', 'may', 'june',
    'july', 'august', 'september', 'october', 'november', 'december',
  ]
  const DATE = /^([A-Za-z]+) ([0-9]{1,2}), ([0-9]{4})$/
  const ORDERS_PATH = '/your-orders/orders'
  const TITLE_MAX = 300
  const NEXT_PARAMS = ['timeFilter', 'page', 'startIndex'] // all a next page needs
  const ITEMS_MAX = 50

  /** Visible text, single-spaced, without invisible format characters. */
  function text(element) {
    if (!element) return ''
    return element.textContent.replace(/\p{Cf}/gu, '').replace(/\s+/g, ' ').trim()
  }

  /** "November 9, 2026" as "2026-11-09"; null for anything else. */
  function isoDate(value) {
    const found = DATE.exec(value)
    if (!found) return null
    const month = MONTHS.indexOf(found[1].toLowerCase())
    const day = Number(found[2])
    if (month < 0 || day < 1 || day > 31) return null
    return `${found[3]}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
  }

  function orderNumber(card) {
    const found = text(card.querySelector('.yohtmlc-order-id [dir="ltr"]'))
    return ORDER.test(found) ? found : null
  }

  /** The first header value that is a date (the header's first column says when it was placed). */
  function orderDate(card) {
    for (const value of card.querySelectorAll('.order-header .order-header__header-list-item')) {
      const found = isoDate(text(value.querySelector('.a-size-base')))
      if (found) return found
    }
    return null
  }

  function quantity(box) {
    const found = text(box.querySelector('.product-image__qty'))
    if (!/^[0-9]{1,3}$/.test(found)) return null
    const value = Number(found)
    return value >= 1 ? value : null
  }

  /** Both layouts: one row per item, and the carousel of a shipment with several. */
  function items(card) {
    const found = []
    for (const box of card.querySelectorAll('.item-box')) {
      const title = text(box.querySelector('.yohtmlc-product-title'))
      if (title) found.push({ title: title.slice(0, TITLE_MAX), quantity: quantity(box) })
    }
    for (const slide of card.querySelectorAll('.yo-enhanced-item-carousel__card')) {
      const title = text(slide.querySelector('.yo-enhanced-title'))
      if (title) found.push({ title: title.slice(0, TITLE_MAX), quantity: null })
    }
    return found.slice(0, ITEMS_MAX)
  }

  /** The next page's address, only if it is another page of the order history, rebuilt with
   * only the parameters that choose the page. */
  function nextPage(doc, base) {
    const last = doc.querySelector('.a-pagination li.a-last')
    if (!last || last.classList.contains('a-disabled')) return null
    const link = last.querySelector('a[href]')
    if (!link) return null
    try {
      const url = new URL(link.getAttribute('href'), base)
      if (url.origin !== 'https://www.amazon.com' || url.pathname !== ORDERS_PATH) return null
      const next = new URL(ORDERS_PATH, 'https://www.amazon.com')
      for (const name of NEXT_PARAMS) {
        const value = url.searchParams.get(name)
        if (value !== null && /^[A-Za-z0-9-]{1,20}$/.test(value)) next.searchParams.set(name, value)
      }
      return next.toString()
    } catch {
      return null
    }
  }

  /** The page's orders, the cards that failed (index and field) and the next page. */
  function read(doc, base = 'https://www.amazon.com/your-orders/orders') {
    const orders = []
    const failed = []
    doc.querySelectorAll('.order-card').forEach((card, index) => {
      const order = orderNumber(card)
      if (!order) return failed.push({ index, field: 'order' })
      const found = items(card)
      if (!found.length) return failed.push({ index, field: 'items' })
      orders.push({ order, date: orderDate(card), items: found })
    })
    return { orders, failed, next: nextPage(doc, base) }
  }

  globalThis.michelitoReader = { read, isoDate }
})()

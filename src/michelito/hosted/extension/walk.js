// The pure parts of the 12-month walk (the background worker does the browsing and sending):
// where it starts, when it stops and what it sends. A classic script: it defines
// `globalThis.michelitoWalk` (the worker loads it with importScripts; the tests import it).
;(() => {
  const ORDERS_URL = 'https://www.amazon.com/your-orders/orders'
  const ORDER = /^[0-9A-Z]{3}-[0-9]{7}-[0-9]{7}$/
  const DAYS = 365
  const BATCH = 20 // orders per request (the server takes at most 20)
  const TITLE_MAX = 300
  const ITEMS_MAX = 50

  function iso(day) {
    return day.toISOString().slice(0, 10)
  }

  /** The first day of the last 12 months, as "YYYY-MM-DD" (local calendar, kept as UTC). */
  function cutoff(today) {
    const start = new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()))
    start.setUTCDate(start.getUTCDate() - DAYS)
    return iso(start)
  }

  /** The order-history pages to start from: this year and, if the cutoff falls in it, the last. */
  function startPages(today) {
    const year = today.getFullYear()
    const years = Number(cutoff(today).slice(0, 4)) < year ? [year, year - 1] : [year]
    return years.map((y) => `${ORDERS_URL}?timeFilter=year-${y}`)
  }

  /** Whether an address is a page the extension may read: the order history, nothing else. */
  function isOrdersPage(address) {
    try {
      const url = new URL(address)
      return url.origin === 'https://www.amazon.com' && url.pathname === '/your-orders/orders'
    } catch {
      return false
    }
  }

  /** The page's orders inside the 12 months (an order without a date is kept), and whether
   * the walk can stop (the page reached orders older than that). */
  function recent(orders, since) {
    const kept = orders.filter((order) => !order.date || order.date >= since)
    return { kept, older: orders.some((order) => order.date && order.date < since) }
  }

  /** What is sent: only the order number and each item's title (and quantity when known). */
  function payload(orders) {
    return orders
      .filter((order) => ORDER.test(order.order))
      .map((order) => ({
        order: order.order,
        items: order.items
          .filter((item) => typeof item.title === 'string' && item.title.trim())
          .slice(0, ITEMS_MAX)
          .map((item) =>
            Number.isInteger(item.quantity) && item.quantity >= 1 && item.quantity <= 999
              ? { title: item.title.slice(0, TITLE_MAX), quantity: item.quantity }
              : { title: item.title.slice(0, TITLE_MAX) },
          ),
      }))
      .filter((order) => order.items.length)
  }

  function batches(list, size = BATCH) {
    const found = []
    for (let start = 0; start < list.length; start += size) found.push(list.slice(start, start + size))
    return found
  }

  /** A pause between pages: slow and a little irregular (2.5 to 4 seconds). */
  function pause(random = Math.random) {
    return 2500 + Math.round(random() * 1500)
  }

  globalThis.michelitoWalk = { cutoff, startPages, isOrdersPage, recent, payload, batches, pause }
})()

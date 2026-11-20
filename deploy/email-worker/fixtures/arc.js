// Synthetic ARC sets for the tests: a throwaway RSA key stands in for Cloudflare's (its public
// half is what the fake resolver "publishes"). Nothing here is a real key or a real message.

const encoder = new TextEncoder()

function b64(bytes) {
  return Buffer.from(bytes).toString('base64')
}

function relaxed(name, value) {
  return `${name.toLowerCase()}:${value.replace(/[ \t]+/g, ' ').trim()}`
}

/** A throwaway signer: { resolver, seal(sets) } where `resolver` answers the DNS TXT lookup. */
export async function signer(domain = 'cloudflare.net', selector = 'arc-2025') {
  const pair = await crypto.subtle.generateKey(
    { name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' },
    true,
    ['sign', 'verify'],
  )
  const spki = b64(new Uint8Array(await crypto.subtle.exportKey('spki', pair.publicKey)))
  const lookups = []
  const resolver = async (name) => {
    lookups.push(name)
    return name === `${selector}._domainkey.${domain}` ? `v=DKIM1; k=rsa; p=${spki}` : null
  }
  /** Header lines (topmost first) for the ARC sets given oldest first, each
   * { aar, ams, seal } (values without the seal's b=); the last one is sealed with the key. */
  async function headers(sets) {
    const lines = []
    const done = []
    for (const [index, set] of sets.entries()) {
      const i = index + 1
      const aar = `i=${i}; ${set.aar}`
      const ams = `i=${i}; ${set.ams ?? 'a=rsa-sha256; d=example.net; s=x; h=from; bh=AAAA; b=AAAA'}`
      let seal = `i=${i}; a=rsa-sha256; t=1700000000; cv=${i === 1 ? 'none' : 'pass'}; d=${set.sealDomain ?? domain}; s=${selector}; b=`
      const signed = [...done, `${relaxed('ARC-Authentication-Results', aar)}\r\n`, `${relaxed('ARC-Message-Signature', ams)}\r\n`, relaxed('ARC-Seal', seal)]
      if (set.sign !== false) {
        const signature = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', pair.privateKey, encoder.encode(signed.join('')))
        seal += b64(new Uint8Array(signature))
      } else {
        seal += 'AAAA'
      }
      done.push(
        `${relaxed('ARC-Authentication-Results', aar)}\r\n`,
        `${relaxed('ARC-Message-Signature', ams)}\r\n`,
        `${relaxed('ARC-Seal', seal)}\r\n`,
      )
      lines.unshift(`ARC-Seal: ${seal}`, `ARC-Message-Signature: ${ams}`, `ARC-Authentication-Results: ${aar}`)
    }
    return lines
  }
  return { resolver, headers, lookups }
}

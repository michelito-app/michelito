# Security

## How to report a vulnerability

Do not open a public issue. Use GitHub's private reporting: the repository's **Security** tab →
**Report a vulnerability**. (Maintainer: this option comes turned off; enable it in Settings →
Code security → Private vulnerability reporting when publishing the repository.) Include which
version or commit you tested, the steps to reproduce it and what impact you think it has.

I answer within a few days. When there is a fix, it is published together with an advisory and,
if you want, with your name in the credits.

## What counts

- The public demo (`demo.<domain>`): seeing or changing another visitor's copy, writing to disk
  outside the copies, getting around the limits, or any way of running code.
- Local mode: the board accepting requests from another site or another machine, data leaving
  your computer, or the PDF password or the Gmail token ending up in a file or in a log.
- The repository containing real personal data.

Do **not** test with anyone's real data or with denial-of-service attacks against the demo. The
demo only has made-up data.

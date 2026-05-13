"""
Custom EDA event source — satellite ground station connectivity monitor.

Polls the ground station health endpoint and yields a url_check event
on every attempt, with status 'OK' or 'Failed'. Unlike the built-in
ansible.eda.url_check, this correctly emits 'Failed' events for connection
errors (ECONNREFUSED, timeout, SSL failure) rather than swallowing them.

Compatible with the url_check event schema so existing rulebook conditions
(event.url_check.status == "Failed") work without modification.
"""

import asyncio
import ssl
import urllib.request


async def main(queue: asyncio.Queue, args: dict):
    url = args.get("url", "")
    delay = int(args.get("delay", 20))
    timeout = int(args.get("timeout", 5))
    # Require this many consecutive failures before emitting a Failed event.
    # Prevents a transient startup failure (skupper not yet linked) from
    # triggering an immediate bootc switch.
    failure_threshold = int(args.get("failure_threshold", 3))

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    consecutive_failures = 0

    while True:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                status = "OK" if resp.status < 500 else "Failed"
        except Exception:
            status = "Failed"

        if status == "OK":
            consecutive_failures = 0
            await queue.put({"url_check": {"url": url, "status": "OK"}})
        else:
            consecutive_failures += 1
            if consecutive_failures >= failure_threshold:
                await queue.put({"url_check": {"url": url, "status": "Failed"}})

        await asyncio.sleep(delay)

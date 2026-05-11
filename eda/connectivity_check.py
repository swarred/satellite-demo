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

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    while True:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                status = "OK" if resp.status < 500 else "Failed"
        except Exception:
            status = "Failed"

        await queue.put({"url_check": {"url": url, "status": status}})
        await asyncio.sleep(delay)

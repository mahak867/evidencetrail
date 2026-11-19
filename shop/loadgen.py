"""Steady synthetic traffic against the shop frontend (about 8 req/s)."""
import asyncio
import os
import random

import httpx

TARGET = os.environ.get("TARGET", "http://frontend:8000/work")
RPS = float(os.environ.get("RPS", "8"))


async def one(c: httpx.AsyncClient):
    try:
        await c.get(TARGET, timeout=10)
    except Exception:
        pass


async def main():
    async with httpx.AsyncClient() as c:
        while True:
            asyncio.create_task(one(c))
            await asyncio.sleep(random.expovariate(RPS))


asyncio.run(main())

"""One process-wide gate for all Keepa work.

Keepa leads and storefront monitoring share one token pool.  Serializing their
high-level jobs prevents the two background loops from exhausting it together.
"""

import asyncio
from datetime import datetime, timezone


class KeepaCoordinator:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.active_job = None
        self.last_job = None
        self.last_finished = None

    async def run(self, name, function, *args):
        async with self.lock:
            self.active_job = name
            try:
                return await asyncio.to_thread(function, *args)
            finally:
                self.last_job = name
                self.last_finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self.active_job = None

    def status(self):
        return {
            "busy": self.lock.locked(),
            "active_job": self.active_job,
            "last_job": self.last_job,
            "last_finished": self.last_finished,
        }


keepa_coordinator = KeepaCoordinator()

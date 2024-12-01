import argparse
import os
import time
from fastapi import FastAPI, Form, UploadFile, File
from prometheus_client import CollectorRegistry, Summary, Counter
import aiohttp
import asyncio
import uvicorn

app = FastAPI()
UPLOAD_DIR = "./worker_logs"
os.makedirs(UPLOAD_DIR, exist_ok=True)

registry = CollectorRegistry()
processed_logs = Counter("processed_logs_total", "Processed log entries", ["worker_id"], registry=registry)

class Worker:
    def __init__(self, worker_id: str, coordinator_url: str):
        self.worker_id = worker_id
        self.coordinator_url = coordinator_url

    async def process_chunk(self, filepath: str, start: int, size: int) -> dict:
        processed_count = 0
        with open(filepath, "r") as file:
            file.seek(start)
            remaining = size
            while remaining > 0:
                line = file.readline()
                if not line:
                    break
                remaining -= len(line)
                parsed = self.parse_log_line(line)
                if parsed:
                    processed_count += 1

        processed_logs.labels(worker_id=self.worker_id).inc(processed_count)
        await self.send_to_coordinator({"processed_count": processed_count})
        return {"processed_count": processed_count}

    @staticmethod
    def parse_log_line(line: str) -> dict:
        try:
            parts = line.split(" ")
            return {"timestamp": parts[0], "level": parts[1], "message": " ".join(parts[2:])}
        except IndexError:
            return None

    async def send_to_coordinator(self, metrics):
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{self.coordinator_url}/collect_results",
                json={"worker_id": self.worker_id, "metrics": metrics}
            )

worker = None

@app.post("/process_chunk")
async def process_chunk(filepath: UploadFile = File(...), start: int = Form(...), size: int = Form(...)):
    file_location = os.path.join(UPLOAD_DIR, filepath.filename)
    with open(file_location, "wb") as file_object:
        file_object.write(await filepath.read())

    result = await worker.process_chunk(file_location, start, size)
    return {"status": "success", "result": result}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Worker Node")
    parser.add_argument("--id", required=True, help="Worker ID")
    parser.add_argument("--coordinator", required=True, help="Coordinator URL")
    parser.add_argument("--port", type=int, default=8001, help="Worker Port")
    args = parser.parse_args()

    worker = Worker(worker_id=args.id, coordinator_url=args.coordinator)
    uvicorn.run("worker:app", host="0.0.0.0", port=args.port, reload=True)


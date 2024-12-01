import argparse
import asyncio
from fastapi import FastAPI, File, Form, UploadFile
from typing import Dict
from pydantic import BaseModel
import aiohttp
from collections import defaultdict
from prometheus_client import start_http_server, generate_latest, CONTENT_TYPE_LATEST, REGISTRY
from fastapi.responses import Response
import os
import argparse
import asyncio
from fastapi import FastAPI, File, Form, UploadFile
from typing import Dict
from pydantic import BaseModel
import aiohttp
from collections import defaultdict
import os

app = FastAPI()
UPLOAD_DIR = "./uploaded_logs"

class Coordinator:
    def __init__(self):
        self.workers = {}
        self.worker_status = {}
        self.results = defaultdict(list)
        os.makedirs(UPLOAD_DIR, exist_ok=True)

    async def register_worker(self, worker_id: str, worker_url: str) -> None:
        self.workers[worker_id] = worker_url
        self.worker_status[worker_id] = "idle"
        print(f"Worker {worker_id} registered at {worker_url}.")

    async def distribute_work(self, filepath: str, chunk_size: int):
        file_size = os.path.getsize(filepath)
        start = 0
        async with aiohttp.ClientSession() as session:
            while start < file_size:
                worker_id = self.get_available_worker()
                if worker_id:
                    worker_url = self.workers[worker_id]
                    try:
                        response = await session.post(
                            f"{worker_url}/process_chunk",
                            json={"filepath": filepath, "start": start, "size": chunk_size},
                        )
                        if response.status == 200:
                            self.worker_status[worker_id] = "busy"
                            start += chunk_size
                        else:
                            print(f"Worker {worker_id} failed: {response.status}")
                    except Exception as e:
                        print(f"Error with Worker {worker_id}: {e}")
                        self.worker_status[worker_id] = "inactive"
                else:
                    print("No workers available. Retrying...")
                    await asyncio.sleep(2)

    def get_available_worker(self) -> str:
        for worker_id, status in self.worker_status.items():
            if status == "idle":
                return worker_id
        return None

    async def collect_results(self, worker_id: str, metrics: Dict) -> None:
        if metrics:
            self.results[worker_id].append(metrics)
            print(f"Metrics from Worker {worker_id}: {metrics}")
        self.worker_status[worker_id] = "idle"

coordinator = Coordinator()

class WorkerRegistration(BaseModel):
    worker_id: str
    worker_url: str

@app.post("/register_worker")
async def register_worker(worker: WorkerRegistration):
    await coordinator.register_worker(worker.worker_id, worker.worker_url)
    return {"status": "Worker registered"}

@app.post("/process_logs")
async def process_logs(filepath: UploadFile = File(...), chunk_size: int = Form(...)):
    file_location = os.path.join(UPLOAD_DIR, filepath.filename)
    with open(file_location, "wb") as file_object:
        file_object.write(filepath.file.read())

    asyncio.create_task(coordinator.distribute_work(file_location, chunk_size))
    return {"status": "Processing started", "filepath": file_location, "chunk_size": chunk_size}

class Metrics(BaseModel):
    worker_id: str
    metrics: dict

@app.post("/collect_results")
async def collect_results(metrics: Metrics):
    await coordinator.collect_results(metrics.worker_id, metrics.metrics)
    return {"status": "Metrics received"}

if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser(description="Log Analyzer Coordinator")
    parser.add_argument("--port", type=int, default=8000, help="Coordinator port")
    args = parser.parse_args()
    uvicorn.run("coordinator:app", host="0.0.0.0", port=args.port, reload=True)



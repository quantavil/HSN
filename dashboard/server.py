import asyncio
import os
import sys
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .indexer import SearchIndexer

# Initialize Indexer
indexer = SearchIndexer()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Background indexing started...")
    asyncio.create_task(run_indexing())
    yield
    # Shutdown (if needed)

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Securely mount only the static assets directory, not the whole dashboard folder
# We ensure the directory exists to avoid errors if it's empty
os.makedirs("dashboard/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")
app.mount("/files", StaticFiles(directory="downloads"), name="files")

class RunConfig(BaseModel):
    action: str = 'all' # 'all', 'import', 'export', 'single'
    chapter: str = ''
    section: str = ''
    force: bool = False
    skip_extras: bool = False
    only_extras: bool = False

class SearchConfig(BaseModel):
    query: str
    scope: str = "all"  # 'all' or specific folder/filename
    fuzzy_threshold: float = 0.85  # 0.0-1.0, default 85% similarity

async def run_indexing():
    try:
        # Run in thread pool to not block async loop
        await asyncio.to_thread(indexer.reindex_all, "downloads")
        print("Background indexing finished.")
    except Exception as e:
        print(f"Indexing failed: {e}")

@app.post("/api/reindex")
async def trigger_reindex():
    asyncio.create_task(run_indexing())
    return {"status": "success", "message": "Re-indexing started in background"}

@app.post("/api/search")
async def search_content(config: SearchConfig):
    """
    Search for text content within PDFs using FTS index with fuzzy matching.
    Runs in threadpool to avoid blocking event loop.
    """
    query = config.query
    fuzzy_threshold = max(0.0, min(1.0, config.fuzzy_threshold))  # Clamp to 0-1
    # Offload blocking SQLite call to thread
    return await asyncio.to_thread(indexer.search, query, config.scope, fuzzy_threshold)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                # Connection likely closed
                pass

manager = ConnectionManager()

# Job Manager to handle process state
class JobManager:
    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.lock = asyncio.Lock()

    async def start_job(self, cmd: List[str]):
        async with self.lock:
            if self.process and self.process.returncode is None:
                raise Exception("A job is already running.")
            
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, 
                cwd=os.getcwd() 
            )
            return self.process

    async def stop_job(self):
        async with self.lock:
            if self.process and self.process.returncode is None:
                self.process.terminate()
                return True
            return False

job_manager = JobManager()

@app.get("/")
async def get():
    # Serve index.html directly from root
    try:
        with open("dashboard/index.html", "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Error: dashboard/index.html not found</h1>", status_code=404)

@app.get("/api/files")
async def list_files():
    """
    Returns a tree or flat list of files in the downloads folder.
    """
    base_path = "downloads"
    result = {}
    
    if not os.path.exists(base_path):
        return {}

    try:
        for folder in os.listdir(base_path):
            folder_path = os.path.join(base_path, folder)
            if os.path.isdir(folder_path):
                files = []
                for f in os.listdir(folder_path):
                    if f.endswith(".pdf"):
                        full_path = os.path.join(folder_path, f)
                        try:
                            stat = os.stat(full_path)
                            files.append({
                                "name": f,
                                "path": f"/files/{folder}/{f}",
                                "size": stat.st_size,
                                "modified": stat.st_mtime
                            })
                        except OSError:
                            continue
                files.sort(key=lambda x: x['name'])
                result[folder] = files
    except Exception as e:
        print(f"Error listing files: {e}")
        return {}
            
    return result

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

async def stream_output(process):
    # Helper to stream stdout/stderr to websockets
    if process.stdout:
        async for line in process.stdout:
            line_str = line.decode().strip()
            if line_str:
                await manager.broadcast(line_str)
    
@app.post("/run")
async def run_script(config: RunConfig):
    # Build command
    cmd = [sys.executable, "extract_dgft_pdfs.py"]
    
    if config.force:
        cmd.append("--force")
    
    if config.chapter:
        cmd.extend(["--chapter", config.chapter])
        
    if config.section:
        cmd.extend(["--section", config.section])
        
    if config.skip_extras:
        cmd.append("--skip-extras")
        
    if config.only_extras:
        cmd.append("--only-extras")

    # Handle action (policy argument)
    if config.action == "import":
        cmd.extend(["--policy", "import"])
    elif config.action == "export":
        cmd.extend(["--policy", "export"])
    else:
        cmd.extend(["--policy", "all"])

    await manager.broadcast(f"> Starting command: {' '.join(cmd)}")

    try:
        # Start subprocess via manager
        process = await job_manager.start_job(cmd)

        # Start streaming in bg task
        asyncio.create_task(monitor_process(process))
        
        return {"status": "success", "message": "Job started"}
    except Exception as e:
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)

async def monitor_process(process):
    await stream_output(process)
    await process.wait()
    await manager.broadcast(f"> Process finished with exit code {process.returncode}")

@app.post("/stop")
async def stop_script():
    stopped = await job_manager.stop_job()
    if stopped:
        await manager.broadcast("> Process terminated by user.")
        return {"status": "success", "message": "Process terminating..."}
    return {"status": "error", "message": "No process running"}


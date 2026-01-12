
import asyncio
import os
import sys
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pydantic import BaseModel
from pypdf import PdfReader

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Mount static files
# We will create the static directory (which is just the current directory for simplicity in this structure)
# or serving from a specific folder. 
# Let's serve everything in 'dashboard' as static for simplicity, 
# or just serve specific files if we want to be cleaner but 'dashboard' dir is fine.
# Actually, let's assume index.html is in dashboard/
app.mount("/static", StaticFiles(directory="dashboard"), name="static")
app.mount("/files", StaticFiles(directory="downloads"), name="files")

from pypdf import PdfReader

class RunConfig(BaseModel):
    action: str = 'all' # 'all', 'import', 'export', 'single'
    chapter: str = ''
    section: str = ''
    force: bool = False
    skip_extras: bool = False
    only_extras: bool = False

# ... (existing code)

class SearchConfig(BaseModel):
    query: str
    scope: str = "all"  # 'all' or specific folder/filename


from .indexer import SearchIndexer

# Initialize Indexer
indexer = SearchIndexer()

@app.on_event("startup")
async def startup_event():
    # Run indexing in background
    asyncio.create_task(run_indexing())

async def run_indexing():
    print("Background indexing started...")
    # Run in thread pool to not block async loop
    await asyncio.to_thread(indexer.reindex_all, "downloads")
    print("Background indexing finished.")

@app.post("/api/reindex")
async def trigger_reindex():
    asyncio.create_task(run_indexing())
    return {"status": "success", "message": "Re-indexing started in background"}

@app.post("/api/search")
async def search_content(config: SearchConfig):
    """
    Search for text content within PDFs using FTS index.
    """
    query = config.query
    return indexer.search(query, config.scope)

current_process = None
connected_websockets: List[WebSocket] = []

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
            except:
                pass

manager = ConnectionManager()

@app.get("/")
async def get():
    # Serve index.html directly from root
    with open("dashboard/index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/files")
async def list_files():
    """
    Returns a tree or flat list of files in the downloads folder.
    Structure:
    {
        "Import_Policy": [{filename, path, size}, ...],
        "Export_Policy": [...],
        ...
    }
    """
    base_path = "downloads"
    result = {}
    
    if not os.path.exists(base_path):
        return {}

    for folder in os.listdir(base_path):
        folder_path = os.path.join(base_path, folder)
        if os.path.isdir(folder_path):
            files = []
            for f in os.listdir(folder_path):
                if f.endswith(".pdf"):
                    full_path = os.path.join(folder_path, f)
                    stat = os.stat(full_path)
                    files.append({
                        "name": f,
                        "path": f"/files/{folder}/{f}",
                        "size": stat.st_size,
                        "modified": stat.st_mtime
                    })
            files.sort(key=lambda x: x['name'])
            result[folder] = files
            
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

async def stream_output(process):
    # Helper to stream stdout/stderr to websockets
    if process.stdout:
        async for line in process.stdout:
            line_str = line.decode().strip()
            if line_str:
                await manager.broadcast(line_str)
    
@app.post("/run")
async def run_script(config: RunConfig):
    global current_process
    
    if current_process and current_process.returncode is None:
        return JSONResponse(content={"status": "error", "message": "A job is already running."}, status_code=400)

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
        # For 'single' updates triggered by the UI, we just rely on --chapter or --section args
        # But we still need to pass a policy type if we know it, or default to all.
        # If the user clicks 'Update' on an Import policy file, we should technically know to use --policy import
        # For now, 'all' is safe as --chapter filters it down anyway.
        cmd.extend(["--policy", "all"])

    await manager.broadcast(f"> Starting command: {' '.join(cmd)}")

    try:
        # Start subprocess
        current_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, 
            cwd=os.getcwd() 
        )

        # Start streaming in bg task
        asyncio.create_task(monitor_process(current_process))
        
        return {"status": "success", "message": "Job started"}
    except Exception as e:
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)

async def monitor_process(process):
    await stream_output(process)
    await process.wait()
    await manager.broadcast(f"> Process finished with exit code {process.returncode}")
    global current_process
    current_process = None

@app.post("/stop")
async def stop_script():
    global current_process
    if current_process and current_process.returncode is None:
        current_process.terminate()
        await manager.broadcast("> Process terminated by user.")
        return {"status": "success", "message": "Process terminating..."}
    return {"status": "error", "message": "No process running"}


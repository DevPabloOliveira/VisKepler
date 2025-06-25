import uvicorn
from fastapi import FastAPI, HTTPException, Request, Query, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.routing import Route, Mount
import geopandas as gpd
import pandas as pd
import os
import json
import glob
import time
import requests
import logging

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO)

# --- Directory Constants ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DATA_DIR = os.path.join(CURRENT_DIR, "data")
STATIC_CONFIG_DIR = os.path.join(CURRENT_DIR, "config")
WEB_DIR = os.path.join(CURRENT_DIR, "web")
ASSETS_DIR = os.path.join(WEB_DIR, "assets")

templates = Jinja2Templates(directory="web/templates")

# --- Application Modules ---
from config.shared import read_configs, load_user_config
from lib.map_utils import create_kepler_map, get_dataId_from_config
from data.load_data import read_geojsons

# --- Global Variables ---
global_config = {"maps": []}
global_maps = {}
user_config = load_user_config()

# --- Shared Directory via Docker Volume ---
SHARED_DIR = "/shared"
os.makedirs(SHARED_DIR, exist_ok=True)

def find_data_file(file_name: str) -> str | None:
    """Searches for a data file in multiple locations (shared and static)."""
    if not file_name:
        return None
    
    # List of locations to search, with priority for the shared directory.
    possible_paths = [
        os.path.join(SHARED_DIR, file_name),
        os.path.join(STATIC_DATA_DIR, file_name)
    ]

    for path in possible_paths:
        if os.path.exists(path):
            logging.info(f"Data file '{file_name}' found at: {path}")
            return path
            
    logging.error(f"Data file '{file_name}' not found in any of the paths: {possible_paths}")
    return None

def create_route_function(map_config):
    """Creates an asynchronous route function for a specific map."""
    async def route_function():
        data_ids = map_config.get("data_ids", {})
        csv_file_name = data_ids.get('csv_file')
        
        data_path = find_data_file(csv_file_name)
        if not data_path:
            return HTMLResponse(content=f"Data file not found: {csv_file_name}", status_code=404)

        try:
            csv_data = pd.read_csv(data_path)
            config = map_config.get("config")
            logging.info(f"Serving map for data_ids: {data_ids}")
            kepler_html = create_kepler_map(None, config, csv_data=csv_data)
            return HTMLResponse(content=kepler_html, status_code=200)
        except Exception as e:
            logging.error(f"Error creating the map for {data_ids}: {e}", exc_info=True)
            return HTMLResponse(content=f"Error creating the map: {e}", status_code=500)

    return route_function

def populate_config():
    """Loads data and configurations on startup."""
    global global_maps, global_config
    
    # Loads data from both the static and shared directories.
    global_maps = read_geojsons(STATIC_DATA_DIR, SHARED_DIR)
    
    global_config["siteTitle"] = user_config.get("siteTitle", "VisKepler Default")

    # Loads maps defined in config.json.
    for map_cfg in user_config.get("maps", []):
        data_ids = map_cfg.get("data_ids", {})
        
        if any(data_id in global_maps for data_id in data_ids.values()):
            config = next(
               (c for c in read_configs(STATIC_CONFIG_DIR) if any(d_id in get_dataId_from_config(c) for d_id in data_ids.values())),
               None,
            )
            map_cfg["config"] = config
            global_config["maps"].append(map_cfg)
        else:
            logging.warning(f"Data for map configuration {map_cfg.get('label')} not found. Skipping.")
    
    # Adds dynamic routes for the loaded maps.
    for map_info in global_config["maps"]:
        link = map_info.get("link")
        if link:
            app.add_api_route(link, create_route_function(map_info), methods=["GET"])
            logging.info(f"Static route created for: {link}")


# --- FastAPI Application Initialization ---
app = FastAPI()

# Mounts the static assets directory.
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

# Loads initial configuration and creates static routes.
populate_config()

# --- Main Routes ---

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Homepage that lists the available maps."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "site_title": global_config.get("siteTitle")
        }
    )

@app.get("/get_config")
async def get_config():
    """Returns the global map configuration to the client."""
    return global_config

@app.get("/consulta_base", response_class=HTMLResponse)
def show_consulta_base(request: Request):
    """Renders the query page."""
    return templates.TemplateResponse("consulta_base.html", {"request": request})

@app.post("/api/upload_map")
async def api_upload_map(
    map_id:   str        = Form(...),
    csv_file: UploadFile = File(...),
    cfg_file: UploadFile = File(...)
):
    """Endpoint for the backend to register a dynamically generated map."""
    try:
        csv_fname = f"{map_id}.csv"
        cfg_fname = f"{map_id}.json"

        # Saves the received files to the shared directory.
        csv_path = os.path.join(SHARED_DIR, csv_fname)
        cfg_path = os.path.join(SHARED_DIR, cfg_fname)

        with open(csv_path, "wb") as f:
            f.write(await csv_file.read())

        cfg_bytes = await cfg_file.read()
        with open(cfg_path, "wb") as f:
            f.write(cfg_bytes)
        
        cfg_json = json.loads(cfg_bytes.decode('utf-8'))
        
        # Creates the dynamic route for the new map.
        link = f"/map/{map_id}"
        map_data = {
            "data_ids": {"csv_file": csv_fname},
            "link": link,
            "label": cfg_json.get("label", map_id),
            "description": cfg_json.get("description", ""),
            "config": cfg_json
        }
        app.add_api_route(link, create_route_function(map_data), methods=["GET"])
        logging.info(f"Map '{map_id}' received via API and route created for: {link}")

        return {"status": "ok", "link": link}

    except Exception as e:
        logging.error(f"Error during API map upload '{map_id}': {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/map/{map_id}", response_class=HTMLResponse)
async def render_map(request: Request, map_id: str):
    """Renders a specific dynamic map. Fallback route."""
    
    config_path = find_data_file(f"{map_id}.json")
    data_path = find_data_file(f"{map_id}.csv")

    if not data_path or not config_path:
        return HTMLResponse("Map not found", status_code=404)

    try:
        df = pd.read_csv(data_path)
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        kepler_html = create_kepler_map(None, config, csv_data=df)
        if isinstance(kepler_html, (bytes, bytearray)):
            kepler_html = kepler_html.decode("utf-8")
        
        return templates.TemplateResponse("map.html", {
            "request": request,
            "map_label": config.get("label", f"Map {map_id}"),
            "kepler_html": kepler_html
        })
    except Exception as e:
        logging.error(f"Error rendering map '{map_id}': {e}", exc_info=True)
        return HTMLResponse(f"Error rendering map: {e}", status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

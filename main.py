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
from typing import Optional

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
    
    # List of locations to search, prioritizing the shared directory.
    possible_paths = [
        os.path.join(SHARED_DIR, file_name),
        os.path.join(STATIC_DATA_DIR, file_name)
    ]

    for path in possible_paths:
        if os.path.exists(path):
            logging.info(f"Arquivo de dados '{file_name}' encontrado em: {path}")
            return path
            
    logging.error(f"Arquivo de dados '{file_name}' não encontrado em nenhum dos caminhos: {possible_paths}")
    return None

def create_route_function(map_config):
    """Creates an asynchronous route function for a specific map."""
    async def route_function():
        data_ids = map_config.get("data_ids", {})
        csv_file_name = data_ids.get('csv_file')
        
        data_path = find_data_file(csv_file_name)
        if not data_path:
            return HTMLResponse(content=f"Arquivo de dados não encontrado: {csv_file_name}", status_code=404)

        try:
            csv_data = pd.read_csv(data_path)
            config = map_config.get("config")
            logging.info(f"Servindo mapa para data_ids: {data_ids}")
            kepler_html = create_kepler_map(csv_data, config) 
            return HTMLResponse(content=kepler_html, status_code=200)
        except Exception as e:
            logging.error(f"Erro ao criar o mapa para {data_ids}: {e}", exc_info=True)
            return HTMLResponse(content=f"Erro ao criar o mapa: {e}", status_code=500)

    return route_function

def populate_config():
    """Loads data and configurations at startup."""
    global global_maps, global_config
    
    # MEMORY LEAK FIX: Loads ONLY static data into global memory.
    # SHARED_DIR was removed from here to avoid loading the entire history into RAM.
    global_maps = read_geojsons(STATIC_DATA_DIR)
    
    global_config["siteTitle"] = user_config.get("siteTitle", "VisKepler Default")

    # Loads maps defined in config.json
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
            logging.warning(f"Dados para a configuração de mapa {map_cfg.get('label')} não encontrados. Pulando.")
    
    # Adds dynamic routes for the loaded maps
    for map_info in global_config["maps"]:
        link = map_info.get("link")
        if link:
            app.add_api_route(link, create_route_function(map_info), methods=["GET"])
            logging.info(f"Rota estática criada para: {link}")


# --- FastAPI Application Initialization ---
app = FastAPI()

# Mounts the static assets directory
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

# Loads initial configuration and creates static routes
populate_config()

# --- Main Routes ---

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """
    New Home: Renders the Landing Page (formerly info.html).
    """
    return templates.TemplateResponse("info.html", {"request": request})

@app.get("/mapas", response_class=HTMLResponse)
async def maps_dashboard(request: Request):
    """
    Old Home: Lists available static and dynamic maps.
    """
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "site_title": global_config.get("siteTitle")
        }
    )

@app.get("/info", response_class=HTMLResponse)
def show_info_page(request: Request):
    """Renders the information and methodology page (alternative route)."""
    return templates.TemplateResponse("info.html", {"request": request})

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
    cfg_file: UploadFile = File(...),
    poly_file: Optional[UploadFile] = File(None)
):
    """
    Endpoint for the backend to register a dynamically generated map.
    Accepts an optional polygon file.
    """
    try:
        csv_fname = f"{map_id}.csv"
        cfg_fname = f"{map_id}.json"

        # Saves received files to the shared directory
        csv_path = os.path.join(SHARED_DIR, csv_fname)
        cfg_path = os.path.join(SHARED_DIR, cfg_fname)

        with open(csv_path, "wb") as f:
            f.write(await csv_file.read())

        cfg_bytes = await cfg_file.read()
        with open(cfg_path, "wb") as f:
            f.write(cfg_bytes)
        
        cfg_json = json.loads(cfg_bytes.decode('utf-8'))
        
        # Saves polygon file if received
        if poly_file:
            # Uses the original name or constructs one based on the ID
            poly_fname = f"poly_{map_id}.csv"
            poly_path = os.path.join(SHARED_DIR, poly_fname)
            with open(poly_path, "wb") as f:
                f.write(await poly_file.read())
            logging.info(f"Arquivo de polígono salvo em: {poly_path}")

        # Creates the dynamic route for the new map
        link = f"/map/{map_id}"
        map_data = {
            "data_ids": {"csv_file": csv_fname},
            "link": link,
            "label": cfg_json.get("label", map_id),
            "description": cfg_json.get("description", ""),
            "config": cfg_json
        }
        
        # Note: app.add_api_route is useful for in-memory persistence, 
        # but the /map/{map_id} route already handles dynamic loading.
        # Kept here for consistency with the legacy static route system.
        app.add_api_route(link, create_route_function(map_data), methods=["GET"])
        logging.info(f"Mapa '{map_id}' recebido via API e rota criada para: {link}")

        return {"status": "ok", "link": link}

    except Exception as e:
        logging.error(f"Erro durante o upload do mapa via API '{map_id}': {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/map/{map_id}", response_class=HTMLResponse)
async def render_map(request: Request, map_id: str):
    """
    Renders a specific dynamic map. 
    Reads the configuration JSON to determine which files to load.
    """
    
    config_fname = f"{map_id}.json"
    config_path = find_data_file(config_fname)

    if not config_path:
        return HTMLResponse("Configuração do mapa não encontrada", status_code=404)

    try:
        # 1. Loads the configuration
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 2. Identifies all necessary data files by looking at the config
        # The get_dataId_from_config function (in lib/map_utils.py) returns a list of dataIds
        data_ids = get_dataId_from_config(config) 
        
        # Dictionary to store DataFrames: {'filename.csv': DataFrame}
        datasets = {} 
        
        for data_id in data_ids:
            # Searches for the file (can be the knn csv or the polygon)
            d_path = find_data_file(data_id)
            if d_path:
                try:
                    # Reads CSV
                    if d_path.endswith('.csv'):
                        df = pd.read_csv(d_path)
                        datasets[data_id] = df
                        logging.info(f"Dados carregados para dataId: {data_id}")
                    # Add logic for geojson if necessary (e.g., if d_path.endswith('.geojson')...)
                except Exception as e:
                    logging.error(f"Erro ao ler dados {data_id}: {e}")
            else:
                logging.warning(f"Arquivo de dados {data_id} referenciado na config não encontrado.")

        if not datasets:
             return HTMLResponse("Nenhum arquivo de dados encontrado para este mapa.", status_code=404)

        # 3. Creates the map passing the datasets dictionary
        # The create_kepler_map function in lib/map_utils.py now accepts a dict
        kepler_html = create_kepler_map(datasets, config)
        
        if isinstance(kepler_html, (bytes, bytearray)):
            kepler_html = kepler_html.decode("utf-8")
        
        return templates.TemplateResponse("map.html", {
            "request": request,
            "map_label": config.get("label", f"Mapa {map_id}"),
            "kepler_html": kepler_html
        })
    except Exception as e:
        logging.error(f"Erro ao renderizar o mapa '{map_id}': {e}", exc_info=True)
        return HTMLResponse(f"Erro ao renderizar o mapa: {e}", status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
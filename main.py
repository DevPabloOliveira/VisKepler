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

import glob, time
import requests 

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(CURRENT_DIR, "web")
ASSETS_DIR = os.path.join(WEB_DIR, "assets")

templates = Jinja2Templates(directory="templates")

# ---- Kepler Configurations ----
from config.shared import read_configs, load_user_config

# ---- Map Libraries ----
from lib.map_utils import create_kepler_map, get_dataId_from_config

# ---- Map Loader ----
from data.load_data import read_geojsons

# ---- Global Configuration ----
global_config = {"maps": []}
global_maps = {}

# Load user configuration from the config.json file
user_config = load_user_config()

DATA_TEMP_DIR   = "./data/temp"
CONFIG_TEMP_DIR = "./config/temp"
os.makedirs(DATA_TEMP_DIR,   exist_ok=True)
os.makedirs(CONFIG_TEMP_DIR, exist_ok=True)

### -----------------------------------------------------------------
### helper: grava arquivos recebidos e cria rota em tempo‑real
### -----------------------------------------------------------------
def _register_uploaded_map(map_id: str, csv_fname: str, cfg_fname: str, cfg: dict):
    link = f"/map/{map_id}"

    # 1) grava/corrige config.json em disco
    cfg_json_path = os.path.join(CONFIG_TEMP_DIR, "config.json")
    try:
        with open(cfg_json_path, "r", encoding="utf-8") as f:
            cfg_file = json.load(f)
    except Exception:
        cfg_file = {"siteTitle": "VisKepler", "maps": []}

    if not any(m["link"] == link for m in cfg_file["maps"]):
        cfg_file["maps"].append({
            "data_ids": {"csv_file": csv_fname},
            "label":    cfg.get("label", map_id),
            "link":     link,
            "description": cfg.get("description", "")
        })
        with open(cfg_json_path, "w", encoding="utf-8") as f:
            json.dump(cfg_file, f, ensure_ascii=False, indent=2)

    # 2) adiciona em memória (+ rota dinâmica)
    global_config["maps"].append({
        "data_ids": {"csv_file": csv_fname},
        "link": link,
        "label": cfg.get("label", map_id),
        "description": cfg.get("description", ""),
        "config": cfg
    })
    app.add_api_route(link, create_route_function(global_config["maps"][-1]), methods=["GET"])



def clean_temp(max_age_hours=24):
    now = time.time()
    for f in glob.glob("./data/temp/knn_*.csv") + glob.glob("./config/temp/knn_*.json"):
        if now - os.path.getmtime(f) > max_age_hours*3600:
            os.remove(f)

# Function to create a dynamic route for each map configuration
def create_route_function(map_config):
   async def route_function():
       data_ids = map_config["data_ids"]
       geojson_data = global_maps.get(data_ids.get('geojson_file'))
       csv_data = global_maps.get(data_ids.get('csv_file')) if 'csv_file' in data_ids else None

       # Check if the required data files are available
       if geojson_data is None and csv_data is None:
           return HTMLResponse(content="Missing data file", status_code=404)

       # Convert GeoJSON data to the appropriate format
       if geojson_data is not None:
           if isinstance(geojson_data, gpd.GeoDataFrame):
               geojson_data = geojson_data.to_json()
           elif isinstance(geojson_data, str):
               geojson_data = gpd.read_file(geojson_data).to_json()

       # Convert CSV data to the appropriate format
       if csv_data is not None:
           if isinstance(csv_data, pd.DataFrame):
               csv_data = csv_data.to_csv(index=False)
           elif isinstance(csv_data, str):
               csv_data = pd.read_csv(csv_data).to_csv(index=False)

       # Support for additional data files if available
       additional_data = []
       for key, value in data_ids.items():
           if key not in ['geojson_file', 'csv_file']:
               additional_data.append(global_maps.get(value))

       config = map_config["config"]
       print(f"Serving map for data_ids: {data_ids}")

       try:
           # Create and serve the Kepler map with the given data and configuration
           kepler_html = create_kepler_map(geojson_data, config, csv_data, additional_data)
           return HTMLResponse(content=kepler_html, status_code=200)
       except Exception as e:
           return HTMLResponse(content=f"Error creating the map: {e}", status_code=500)

   return route_function

# Function to populate the global configuration and load map data
def populate_config():
   global global_maps
   global_maps = read_geojsons("./data", "./data/temp", "./config/temp")
   
   # Adding siteTitle to global_config from user configuration
   global_config["siteTitle"] = user_config.get("siteTitle", "Default Title")

   # Loop through each map configuration from user config
   for map_config in user_config["maps"]:
       data_ids = map_config["data_ids"]
       link = map_config["link"]
       label = map_config["label"]

       # Find the corresponding configuration from available configs
       config = next(
           (
               config
               for config in read_configs("./config")
               if any(data_id in get_dataId_from_config(config) for data_id in data_ids.values())
           ),
           None,
       )

       # Check if data files exist in global maps and add to the global configuration
       if data_ids.get('geojson_file') in global_maps or data_ids.get('csv_file') in global_maps:
           global_config["maps"].append({
               "data_ids": data_ids,
               "link": link,
               "label": label,
               "description": map_config.get("description", ""),
               "config": config,
           })

populate_config()

# ---- API ENTRYPOINT ----

templates = Jinja2Templates(directory="web/templates")

app = FastAPI()

app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "site_title": global_config["siteTitle"]
        }
    )

# Endpoint to get the global configuration
@app.get("/get_config")
async def get_config():
   return global_config

# Endpoint to retrieve specific map information by map_id
@app.get("/get_map_info/{map_id}")
async def get_map_info(map_id: str):
   print(f"Received map_id: {map_id}")  # Log to check the received mapId

   # Loop through all maps to find the requested map information
   for map in global_config["maps"]:
       if 'geojson_file' in map["data_ids"] and map["data_ids"]["geojson_file"].split('.')[0] == map_id:
           print(f"Found map info for geojson_file: {map['data_ids']['geojson_file']}")  # Log for GeoJSON file
           return JSONResponse(map)
       elif 'csv_file' in map["data_ids"] and map["data_ids"]["csv_file"].split('.')[0] == map_id:
           print(f"Found map info for csv_file: {map['data_ids']['csv_file']}")  # Log for CSV file
           return JSONResponse(map)

   print(f"Map info not found for map_id: {map_id}")  # Log if mapId was not found
   raise HTTPException(status_code=404, detail="Map not found")

# ---- Create dynamic routes for each map configuration ----
for map_config in global_config["maps"]:
   if 'geojson_file' in map_config['data_ids']:
       route = f"/{map_config['data_ids']['geojson_file'].split('.')[0]}"
   elif 'csv_file' in map_config['data_ids']:
       route = f"/{map_config['data_ids']['csv_file'].split('.')[0]}"
   print(f"Adding route: {route} for data_ids: {map_config['data_ids']}")  # Log route addition
   app.add_api_route(route, create_route_function(map_config), methods=["GET"])

# Endpoint to list all available routes
@app.get("/routes")
async def get_routes():
    routes = []
    for route in app.routes:
        if isinstance(route, Route):
            routes.append(
                {"path": route.path, "name": route.name, "methods": list(route.methods)}
            )
        elif isinstance(route, Mount):
            routes.append(
                {"path": route.path, "name": route.name, "methods": "N/A (Mount)"}
            )
    return {"routes": routes}

@app.get("/consulta_base", response_class=HTMLResponse)
def show_consulta_base(request: Request):
    return templates.TemplateResponse("consulta_base.html", {"request": request})


@app.get("/consulta_base/mapa", response_class=HTMLResponse)
async def show_consulta_base_mapa(
    request: Request,
    uf: str,
    municipio: str,
    tipo: str
):
    # Lógica para carregar CSV + CONFIG do mapa gerado
    map_id = f"knn_{time.strftime('%Y%m%d')}_latest"
    # Ajuste para capturar o arquivo mais recente com base nos parâmetros, se necessário

    # Caminhos
    data_path = f"./data/temp/{map_id}.csv"
    config_path = f"./config/temp/{map_id}.json"

    if not os.path.exists(data_path) or not os.path.exists(config_path):
        return HTMLResponse("Mapa não encontrado", status_code=404)

    # Leitura dos dados
    df = pd.read_csv(data_path)
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # Aqui o ajuste: passa o CSV como csv_data
    kepler_html = create_kepler_map(None, config, csv_data=df)
    if isinstance(kepler_html, (bytes, bytearray)):
        kepler_html = kepler_html.decode("utf-8")

    return templates.TemplateResponse("map.html", {
        "request": request,
        "map_label": f"Mapa de Alocação – {municipio}/{uf}",
        "kepler_html": kepler_html
    })

CONFIG_TEMP_DIR = "./config/temp"

# endpoint /refresh_config
@app.get("/refresh_config")
async def refresh_config(map_id: str = Query(...)):
    filepath = os.path.join(CONFIG_TEMP_DIR, f"{map_id}.json")
    if not os.path.exists(filepath):
        return JSONResponse(status_code=404, content={"error": "Config not found"})
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["status"] = "ok"
        return JSONResponse(content=data)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@app.post("/api/upload_map")
async def api_upload_map(
    map_id:   str        = Form(...),
    csv_file: UploadFile = File(...),
    cfg_file: UploadFile = File(...)
):
    try:
        csv_fname = f"{map_id}.csv"
        cfg_fname = f"{map_id}.json"

        csv_path = os.path.join(DATA_TEMP_DIR,   csv_fname)
        cfg_path = os.path.join(CONFIG_TEMP_DIR, cfg_fname)

        with open(csv_path, "wb") as f:
            f.write(await csv_file.read())

        cfg_bytes = await cfg_file.read()
        with open(cfg_path, "wb") as f:
            f.write(cfg_bytes)
        cfg_json = json.loads(cfg_bytes.decode())

        _register_uploaded_map(map_id, csv_fname, cfg_fname, cfg_json)
        return {"status": "ok", "link": f"/map/{map_id}"}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/map/{map_id}", response_class=HTMLResponse)
async def render_map(request: Request, map_id: str):
    data_path = os.path.join("./data/temp", f"{map_id}.csv")
    config_path = os.path.join("./config/temp", f"{map_id}.json")

    if not os.path.exists(data_path) or not os.path.exists(config_path):
        return HTMLResponse("Mapa não encontrado", status_code=404)

    df = pd.read_csv(data_path)
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # Garante que o DataFrame do CSV seja passado como csv_data
    kepler_html = create_kepler_map(None, config, csv_data=df)
    if isinstance(kepler_html, (bytes, bytearray)):
        kepler_html = kepler_html.decode("utf-8")
    
    return templates.TemplateResponse("map.html", {
        "request": request,
        "map_label": config.get("label", f"Mapa {map_id}"),
        "kepler_html": kepler_html
    })
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
import re
import secrets
import math
import unicodedata
from typing import Optional

from fastapi import Header

# --- Configuração de Logging ---
logging.basicConfig(level=logging.INFO)

# --- Constantes de Diretório ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DATA_DIR = os.path.join(CURRENT_DIR, "data")
STATIC_CONFIG_DIR = os.path.join(CURRENT_DIR, "config")
WEB_DIR = os.path.join(CURRENT_DIR, "web")
ASSETS_DIR = os.path.join(WEB_DIR, "assets")
STATIC_POLYGON_DIR_CANDIDATES = [
    os.path.join(CURRENT_DIR, "backend_data", "geojson_por_estado_cidade"),
    os.path.abspath(os.path.join(CURRENT_DIR, "..", "backend_data", "geojson_por_estado_cidade")),
    "/backend_data/geojson_por_estado_cidade",
]
STATIC_POLYGON_DIR = next((path for path in STATIC_POLYGON_DIR_CANDIDATES if os.path.isdir(path)), STATIC_POLYGON_DIR_CANDIDATES[0])

templates = Jinja2Templates(directory="web/templates")

# --- Módulos da Aplicação ---
from config.shared import read_configs, load_user_config
from lib.map_utils import create_kepler_map, get_dataId_from_config
from data.load_data import read_geojsons

# --- Variáveis Globais ---
global_config = {"maps": []}
global_maps = {}
user_config = load_user_config() or {}

# --- Diretório Compartilhado via Docker Volume ---
SHARED_DIR = "/shared"
os.makedirs(SHARED_DIR, exist_ok=True)

MAP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ALLOWED_DATA_EXTENSIONS = {".csv", ".geojson", ".json"}
UPLOAD_TOKEN = os.getenv("MAP_UPLOAD_TOKEN", "")

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        logging.warning("Valor inválido em %s. Usando padrão %s.", name, default)
        return default

UPLOAD_MAX_BYTES = _env_int("MAP_UPLOAD_MAX_BYTES", 100 * 1024 * 1024)
CONFIG_MAX_BYTES = _env_int("MAP_CONFIG_MAX_BYTES", 10 * 1024 * 1024)

def validate_upload_token(token: str | None) -> None:
    if UPLOAD_TOKEN and not secrets.compare_digest(token or "", UPLOAD_TOKEN):
        raise HTTPException(status_code=401, detail="Token de upload inválido.")

def sanitize_map_id(map_id: str) -> str:
    if not MAP_ID_RE.fullmatch(map_id or ""):
        raise HTTPException(status_code=400, detail="map_id inválido.")
    return map_id

def validate_data_filename(file_name: str, allowed_extensions: set[str] = ALLOWED_DATA_EXTENSIONS) -> str:
    if not file_name:
        raise HTTPException(status_code=400, detail="Nome de arquivo vazio.")
    if os.path.basename(file_name) != file_name or os.path.isabs(file_name) or ".." in file_name:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")
    if os.path.splitext(file_name)[1].lower() not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Extensão de arquivo inválida.")
    return file_name

def safe_join(base_dir: str, file_name: str) -> str:
    safe_name = validate_data_filename(file_name)
    base_abs = os.path.abspath(base_dir)
    target = os.path.abspath(os.path.join(base_abs, safe_name))
    if os.path.commonpath([base_abs, target]) != base_abs:
        raise HTTPException(status_code=400, detail="Caminho de arquivo inválido.")
    return target

def _normalize_key(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.upper().replace(" ", "_").strip()

def _calculate_optimal_view_from_points(df: pd.DataFrame):
    required = {"Origin_Lat", "Origin_Lon", "Destination_Lat", "Destination_Lon"}
    if df.empty or not required.issubset(df.columns):
        return -14.2350, -51.9253, 4

    lats = pd.concat(
        [pd.to_numeric(df["Origin_Lat"], errors="coerce"), pd.to_numeric(df["Destination_Lat"], errors="coerce")],
        ignore_index=True,
    ).dropna()
    lons = pd.concat(
        [pd.to_numeric(df["Origin_Lon"], errors="coerce"), pd.to_numeric(df["Destination_Lon"], errors="coerce")],
        ignore_index=True,
    ).dropna()
    if lats.empty or lons.empty:
        return -14.2350, -51.9253, 4

    min_lat, max_lat = float(lats.min()), float(lats.max())
    min_lon, max_lon = float(lons.min()), float(lons.max())
    center_lat = (min_lat + max_lat) / 2
    center_lon = (min_lon + max_lon) / 2
    max_dif = max(max_lat - min_lat, max_lon - min_lon)
    if max_dif == 0:
        return center_lat, center_lon, 12
    zoom = math.log2(360 / max_dif) + 1.15
    zoom = max(min(zoom, 14), 4)
    return center_lat, center_lon, zoom

def _find_polygon_dataset(city: str, state: str):
    if not city or not state:
        return None, None
    state_dir = os.path.join(STATIC_POLYGON_DIR, _normalize_key(state))
    if not os.path.isdir(state_dir):
        return None, None

    target_name = _normalize_key(city)
    polygon_path = None
    for candidate in os.listdir(state_dir):
        if not candidate.lower().endswith(".geojson"):
            continue
        candidate_base = os.path.splitext(candidate)[0]
        if _normalize_key(candidate_base) == target_name:
            polygon_path = os.path.join(state_dir, candidate)
            break

    if not polygon_path or not os.path.exists(polygon_path):
        return None, None

    try:
        polygon_gdf = gpd.read_file(polygon_path)
        return os.path.basename(polygon_path), polygon_gdf
    except Exception as exc:
        logging.warning("Falha ao carregar poligono %s: %s", polygon_path, exc)
        return None, None

def _build_static_ubs_df(csv_data: pd.DataFrame) -> pd.DataFrame:
    required = {"opportunity_name", "Destination_Lat", "Destination_Lon", "distance_km"}
    if csv_data.empty or not required.issubset(csv_data.columns):
        return pd.DataFrame()

    data = csv_data.copy()
    for col in ["Destination_Lat", "Destination_Lon", "distance_km"]:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["Destination_Lat", "Destination_Lon"])
    if data.empty:
        return pd.DataFrame()

    rows = []
    for (name, lat, lon), group in data.groupby(["opportunity_name", "Destination_Lat", "Destination_Lon"], dropna=False):
        distances = pd.to_numeric(group["distance_km"], errors="coerce")
        critical_mask = distances > 4
        rows.append({
            "UBS": str(name or ""),
            "UBS curta": (str(name or "")[:27] + "…") if len(str(name or "")) > 28 else str(name or ""),
            "Destination_Lat": lat,
            "Destination_Lon": lon,
            "setores_alocados": int(len(group)),
            "distancia_media_km": float(distances.mean()) if distances.notna().any() else None,
            "distancia_maxima_km": float(distances.max()) if distances.notna().any() else None,
            "setores_criticos": int(critical_mask.fillna(False).sum()),
        })

    ubs_df = pd.DataFrame(rows)
    if ubs_df.empty:
        return ubs_df

    mean_distance = pd.to_numeric(ubs_df["distancia_media_km"], errors="coerce")
    critical_mask = mean_distance.gt(4) | pd.to_numeric(ubs_df["setores_criticos"], errors="coerce").fillna(0).gt(0)
    ubs_df["Critical_UBS_Lat"] = ubs_df["Destination_Lat"].where(critical_mask)
    ubs_df["Critical_UBS_Lon"] = ubs_df["Destination_Lon"].where(critical_mask)
    ubs_df["Classe da UBS"] = mean_distance.apply(
        lambda d: "Crítica (> 4 km)" if pd.notna(d) and d > 4 else ("Atenção (2-4 km)" if pd.notna(d) and d > 2 else "Adequada (≤ 2 km)")
    )
    return ubs_df

def _build_static_published_config(csv_filename: str, label: str, center_lat: float, center_lon: float, zoom: float, polygon_filename: str | None, ubs_filename: str | None, show_labels: bool):
    def field(name: str, field_type: str = "real") -> dict:
        return {"name": name, "type": field_type}

    ACCESS_RANGE = {
        "name": "Acessibilidade IPSUM",
        "type": "sequential",
        "category": "Custom",
        "colors": ["#38BDF8", "#22D3EE", "#A3E635", "#FACC15", "#FB923C", "#EF4444", "#7F1D1D"],
        "reversed": False,
    }

    def point_layer(layer_id, map_data_id, layer_label, color, lat, lon, radius, opacity, *, color_field=None, size_field=None, radius_range=None, outline=False, stroke_color=None, text_labels=None):
        return {
            "id": layer_id,
            "type": "point",
            "config": {
                "dataId": map_data_id,
                "label": layer_label,
                "color": color,
                "highlightColor": [252, 242, 26, 255],
                "columns": {"lat": lat, "lng": lon, "altitude": None},
                "isVisible": True,
                "visConfig": {
                    "radius": radius,
                    "fixedRadius": False,
                    "opacity": opacity,
                    "outline": outline,
                    "thickness": 2,
                    "strokeColor": stroke_color,
                    "radiusRange": radius_range or [4, 26],
                    "filled": True,
                    "colorRange": ACCESS_RANGE,
                },
                "hidden": False,
                "textLabel": text_labels or [],
            },
            "visualChannels": {
                "colorField": color_field,
                "colorScale": "quantile",
                "strokeColorField": None,
                "strokeColorScale": "quantile",
                "sizeField": size_field,
                "sizeScale": "sqrt",
            },
        }

    layers = []

    layers.append(point_layer(
        secrets.token_hex(4), csv_filename, "Setores de demanda",
        [255, 77, 77], "Origin_Lat", "Origin_Lon", 4, 0.16,
        size_field=None, radius_range=[1, 6]
    ))

    layers.append(point_layer(
        secrets.token_hex(4), csv_filename, "Setores críticos (> 4 km)",
        [255, 77, 77], "Origin_Lat", "Origin_Lon", 9, 0.82,
        color_field=field("distance_km"), size_field=None, radius_range=[4, 12],
        outline=True, stroke_color=[255, 209, 102]
    ))

    if ubs_filename:
        text_labels = [{
            "field": field("UBS curta", "string"),
            "color": [255, 255, 255],
            "size": 11,
            "offset": [0, -10],
            "anchor": "start",
            "alignment": "center",
        }] if show_labels else []
        layers.append(point_layer(
            secrets.token_hex(4), ubs_filename, "UBS por setores alocados",
            [31, 186, 214], "Destination_Lat", "Destination_Lon", 10, 0.92,
            size_field=field("setores_alocados", "integer"), radius_range=[7, 20],
            outline=True, stroke_color=[255, 255, 255], text_labels=text_labels
        ))
        layers.append(point_layer(
            secrets.token_hex(4), ubs_filename, "UBS críticas",
            [31, 186, 214], "Critical_UBS_Lat", "Critical_UBS_Lon", 13, 0.95,
            size_field=field("setores_criticos", "integer"), radius_range=[9, 22],
            outline=True, stroke_color=[255, 209, 102], text_labels=text_labels
        ))
    else:
        layers.append(point_layer(
            secrets.token_hex(4), csv_filename, "UBS",
            [31, 186, 214], "Destination_Lat", "Destination_Lon", 9, 0.9,
            outline=True, stroke_color=[255, 255, 255], radius_range=[6, 12]
        ))

    layers.append({
        "id": secrets.token_hex(4),
        "type": "arc",
        "config": {
            "dataId": csv_filename,
            "label": "Fluxos de alocação",
            "color": [56, 189, 248],
            "highlightColor": [255, 255, 255],
            "columns": {"lat0": "Origin_Lat", "lng0": "Origin_Lon", "lat1": "Destination_Lat", "lng1": "Destination_Lon"},
            "isVisible": True,
            "visConfig": {
                "opacity": 0.34,
                "thickness": 1.2,
                "sizeRange": [0, 10],
                "colorRange": ACCESS_RANGE,
            },
            "hidden": False,
            "textLabel": [],
        },
        "visualChannels": {
            "colorField": field("distance_km"),
            "colorScale": "quantile",
            "sizeField": None,
            "sizeScale": "sqrt",
        },
    })

    if polygon_filename:
        layers.append({
            "id": secrets.token_hex(4),
            "type": "geojson",
            "config": {
                "dataId": polygon_filename,
                "label": "Limite Municipal",
                "color": [255, 209, 102],
                "columns": {"geojson": "geometry"},
                "isVisible": True,
                "visConfig": {
                    "opacity": 0.01,
                    "strokeOpacity": 0.98,
                    "thickness": 2.6,
                    "strokeColor": [255, 209, 102],
                    "radius": 10,
                    "sizeRange": [0, 10],
                    "radiusRange": [0, 50],
                    "heightRange": [0, 0],
                    "elevationScale": 5,
                    "stroked": True,
                    "filled": False,
                    "enable3d": False,
                    "wireframe": False,
                },
                "hidden": False,
                "textLabel": [],
            },
            "visualChannels": {
                "colorField": None,
                "colorScale": "quantile",
                "strokeColorField": None,
                "strokeColorScale": "quantile",
                "sizeField": None,
                "sizeScale": "linear",
            },
        })

    layers.append({
        "id": secrets.token_hex(4),
        "type": "line",
        "config": {
            "dataId": csv_filename,
            "label": "Linhas origem-destino",
            "color": [148, 163, 184],
            "highlightColor": [252, 242, 26, 255],
            "columns": {"lat0": "Origin_Lat", "lng0": "Origin_Lon", "alt0": None, "lat1": "Destination_Lat", "lng1": "Destination_Lon", "alt1": None},
            "isVisible": False,
            "visConfig": {"opacity": 0.26, "thickness": 0.8},
            "hidden": False,
            "textLabel": [],
        },
    })

    fields_to_show = {
        csv_filename: [
            {"name": "demand_id"},
            {"name": "Destination_City"},
            {"name": "Destination_State"},
            {"name": "opportunity_name"},
            {"name": "distance_km"},
        ]
    }
    if ubs_filename:
        fields_to_show[ubs_filename] = [
            {"name": "UBS"},
            {"name": "setores_alocados"},
            {"name": "distancia_media_km"},
            {"name": "distancia_maxima_km"},
            {"name": "Classe da UBS"},
        ]
    if polygon_filename:
        fields_to_show[polygon_filename] = [{"name": "NM_MUN"}, {"name": "SIGLA_UF"}]

    return {
        "version": "v1",
        "config": {
            "visState": {
                "filters": [],
                "layers": layers,
                "interactionConfig": {"tooltip": {"fieldsToShow": fields_to_show, "enabled": True}},
                "layerBlending": "normal",
                "splitMaps": [],
            },
            "mapState": {
                "bearing": 0,
                "dragRotate": True,
                "latitude": round(center_lat, 6),
                "longitude": round(center_lon, 6),
                "pitch": 38,
                "zoom": zoom,
                "isSplit": False,
            },
            "mapStyle": {"styleType": "dark"},
        },
        "label": label,
    }

def _build_published_map_bundle(map_config: dict, csv_file_name: str, csv_data: pd.DataFrame):
    required = {"Origin_Lat", "Origin_Lon", "Destination_Lat", "Destination_Lon", "distance_km", "Destination_City", "Destination_State"}
    if csv_data.empty or not required.issubset(csv_data.columns):
        return None

    city = str(csv_data["Destination_City"].dropna().iloc[0]) if csv_data["Destination_City"].dropna().any() else ""
    state = str(csv_data["Destination_State"].dropna().iloc[0]) if csv_data["Destination_State"].dropna().any() else ""
    polygon_filename, polygon_gdf = _find_polygon_dataset(city, state)

    ubs_df = _build_static_ubs_df(csv_data)
    ubs_filename = f"{os.path.splitext(csv_file_name)[0]}_ubs.csv" if not ubs_df.empty else None
    center_lat, center_lon, zoom = _calculate_optimal_view_from_points(csv_data)
    if polygon_gdf is not None and not polygon_gdf.empty and hasattr(polygon_gdf, "total_bounds"):
        minx, miny, maxx, maxy = polygon_gdf.total_bounds
        center_lon = float((minx + maxx) / 2)
        center_lat = float((miny + maxy) / 2)
        max_dif = max(float(maxx - minx), float(maxy - miny))
        if max_dif > 0:
            zoom = max(min(math.log2(360 / max_dif) + 0.75, 14), 4)
    else:
        zoom = max(zoom - 0.35, 4)

    config = _build_static_published_config(
        csv_file_name,
        map_config.get("label", "Mapa publicado"),
        center_lat,
        center_lon,
        zoom,
        polygon_filename,
        ubs_filename,
        show_labels=not ubs_df.empty and len(ubs_df) <= 60,
    )

    datasets = {csv_file_name: csv_data}
    if polygon_filename and polygon_gdf is not None:
        datasets[polygon_filename] = polygon_gdf
    if ubs_filename and not ubs_df.empty:
        datasets[ubs_filename] = ubs_df
    return {"config": config, "datasets": datasets}

def normalize_kepler_html(kepler_html: str, title: str) -> str:
    """Prepara o HTML gerado pelo Kepler para abrir como pagina full-screen."""
    fullscreen_css = """
  <style id="ipsum-kepler-fullscreen">
    html,
    body {
      width: 100%;
      height: 100%;
      margin: 0 !important;
      padding: 0 !important;
      overflow: hidden !important;
      background: #0d1824;
    }

    body > div[style*="100vw"] {
      position: fixed !important;
      inset: 0 !important;
      width: 100% !important;
      height: 100% !important;
    }

    #app-content,
    .keplergl-widget-container,
    .kepler-gl {
      width: 100% !important;
      height: 100% !important;
    }
  </style>
"""
    safe_title = (
        title.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    html = kepler_html.replace("<title>Kepler.gl</title>", f"<title>{safe_title}</title>", 1)

    if "</head>" in html:
        html = html.replace("</head>", f"{fullscreen_css}</head>", 1)
    else:
        html = f"<!DOCTYPE html><html><head><title>{safe_title}</title>{fullscreen_css}</head><body>{html}</body></html>"

    return html

async def read_upload_file(upload: UploadFile, max_bytes: int) -> bytes:
    content = await upload.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="Arquivo excede o limite permitido.")
    return content

def find_data_file(file_name: str) -> str | None:
    """Procura um arquivo de dados em múltiplos locais (compartilhado e estático)."""
    if not file_name:
        return None
    try:
        safe_name = validate_data_filename(file_name)
    except HTTPException as exc:
        logging.warning("Nome de arquivo rejeitado: %s", file_name)
        raise exc
    
    # Lista de locais para procurar, com prioridade para o compartilhado.
    possible_paths = [
        safe_join(SHARED_DIR, safe_name),
        safe_join(STATIC_DATA_DIR, safe_name)
    ]

    for path in possible_paths:
        if os.path.exists(path):
            logging.info(f"Arquivo de dados '{file_name}' encontrado em: {path}")
            return path
            
    logging.error(f"Arquivo de dados '{file_name}' não encontrado em nenhum dos caminhos: {possible_paths}")
    return None

def create_route_function(map_config):
    """Cria uma função de rota assíncrona para um mapa específico."""
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
            published_bundle = _build_published_map_bundle(map_config, csv_file_name, csv_data)
            if published_bundle:
                kepler_html = create_kepler_map(published_bundle["datasets"], published_bundle["config"])
            else:
                kepler_html = create_kepler_map(csv_data, config)
            return HTMLResponse(content=kepler_html, status_code=200)
        except Exception as e:
            logging.error(f"Erro ao criar o mapa para {data_ids}: {e}", exc_info=True)
            return HTMLResponse(content=f"Erro ao criar o mapa: {e}", status_code=500)

    return route_function

def populate_config():
    """Carrega dados e configurações na inicialização."""
    global global_maps, global_config
    
    # CORREÇÃO MEMORY LEAK: Carrega APENAS dados estáticos para a memória global.
    global_maps = read_geojsons(STATIC_DATA_DIR)
    
    global_config["siteTitle"] = user_config.get("siteTitle", "VisKepler Default")

    # Carrega mapas definidos em config.json
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
    
    # Adiciona rotas dinâmicas para os mapas carregados
    for map_info in global_config["maps"]:
        link = map_info.get("link")
        if link:
            app.add_api_route(link, create_route_function(map_info), methods=["GET"])
            logging.info(f"Rota estática criada para: {link}")


app = FastAPI()
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

# Carrega a configuração inicial e cria rotas estáticas
populate_config()

# --- Rotas Principais ---

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """
    Nova Home: Renderiza a Landing Page (antiga info.html).
    """
    return templates.TemplateResponse("info.html", {"request": request})

@app.get("/mapas", response_class=HTMLResponse)
async def maps_dashboard(request: Request):
    """
    Antiga Home: Lista os mapas estáticos e dinâmicos disponíveis.
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
    """Renderiza a página de informações e metodologia (rota alternativa)."""
    return templates.TemplateResponse("info.html", {"request": request})

@app.get("/get_config")
async def get_config():
    """Retorna a configuração global de mapas para o cliente."""
    return global_config

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/consulta_base", response_class=HTMLResponse)
def show_consulta_base(request: Request):
    """Renderiza a página de consulta."""
    return templates.TemplateResponse("consulta_base.html", {"request": request})

@app.post("/api/upload_map")
async def api_upload_map(
    map_id:   str        = Form(...),
    csv_file: UploadFile = File(...),
    cfg_file: UploadFile = File(...),
    poly_file: Optional[UploadFile] = File(None),
    ubs_file: Optional[UploadFile] = File(None),
    x_upload_token: Optional[str] = Header(default=None)
):
    """
    Endpoint para o backend registrar um mapa gerado dinamicamente.
    Aceita arquivo de polígono opcional.
    """
    try:
        validate_upload_token(x_upload_token)
        map_id = sanitize_map_id(map_id)

        csv_fname = f"{map_id}.csv"
        cfg_fname = f"{map_id}.json"
        poly_fname = f"poly_{map_id}.csv" if poly_file else None
        ubs_fname = f"ubs_{map_id}.csv" if ubs_file else None

        cfg_bytes = await read_upload_file(cfg_file, CONFIG_MAX_BYTES)
        try:
            cfg_json = json.loads(cfg_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"JSON de configuração inválido: {exc.msg}")
        if not isinstance(cfg_json, dict):
            raise HTTPException(status_code=400, detail="JSON de configuração deve ser um objeto.")

        allowed_data_ids = {csv_fname}
        if poly_fname:
            allowed_data_ids.add(poly_fname)
        if ubs_fname:
            allowed_data_ids.add(ubs_fname)
        referenced_data_ids = set(get_dataId_from_config(cfg_json))
        unexpected_data_ids = referenced_data_ids - allowed_data_ids
        if unexpected_data_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Configuração referencia arquivos não enviados: {sorted(unexpected_data_ids)}"
            )

        csv_bytes = await read_upload_file(csv_file, UPLOAD_MAX_BYTES)
        poly_bytes = await read_upload_file(poly_file, UPLOAD_MAX_BYTES) if poly_file else None
        ubs_bytes = await read_upload_file(ubs_file, UPLOAD_MAX_BYTES) if ubs_file else None

        csv_path = safe_join(SHARED_DIR, csv_fname)
        cfg_path = safe_join(SHARED_DIR, cfg_fname)

        with open(csv_path, "wb") as f:
            f.write(csv_bytes)

        with open(cfg_path, "wb") as f:
            f.write(cfg_bytes)

        if poly_fname and poly_bytes is not None:
            poly_path = safe_join(SHARED_DIR, poly_fname)
            with open(poly_path, "wb") as f:
                f.write(poly_bytes)
            logging.info(f"Arquivo de polígono salvo em: {poly_path}")

        if ubs_fname and ubs_bytes is not None:
            ubs_path = safe_join(SHARED_DIR, ubs_fname)
            with open(ubs_path, "wb") as f:
                f.write(ubs_bytes)
            logging.info(f"Arquivo agregado de UBS salvo em: {ubs_path}")

        # Cria a rota dinâmica para o novo mapa
        link = f"/map/{map_id}"
        map_data = {
            "data_ids": {"csv_file": csv_fname, "ubs_file": ubs_fname, "poly_file": poly_fname},
            "link": link,
            "label": cfg_json.get("label", map_id),
            "description": cfg_json.get("description", ""),
            "config": cfg_json
        }
        
        # Nota: app.add_api_route é útil para persistência em memória, 
        # mas a rota /map/{map_id} já cuida do carregamento dinâmico.
        # Mantemos aqui para consistência com o sistema legado de rotas estáticas.
        app.add_api_route(link, create_route_function(map_data), methods=["GET"])
        logging.info(f"Mapa '{map_id}' recebido via API e rota criada para: {link}")

        return {"status": "ok", "link": link}

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Erro durante o upload do mapa via API '{map_id}': {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/map/{map_id}", response_class=HTMLResponse)
async def render_map(request: Request, map_id: str):
    """
    Renderiza um mapa dinâmico específico. 
    Lê o JSON de configuração para descobrir quais arquivos carregar.
    """
    map_id = sanitize_map_id(map_id)
    config_fname = f"{map_id}.json"
    config_path = find_data_file(config_fname)

    if not config_path:
        return HTMLResponse("Configuração do mapa não encontrada", status_code=404)

    try:
        # 1. Carrega a configuração
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 2. Identifica todos os arquivos de dados necessários olhando a config
        # A função get_dataId_from_config (em lib/map_utils.py) retorna lista de dataIds
        data_ids = get_dataId_from_config(config) 
        
        # Dicionário para armazenar os DataFrames: {'nome_arquivo.csv': DataFrame}
        datasets = {} 
        
        for data_id in data_ids:
            # Procura o arquivo (pode ser o csv do knn ou do polígono)
            d_path = find_data_file(data_id)
            if d_path:
                try:
                    if d_path.endswith('.csv'):
                        df = pd.read_csv(d_path)
                        datasets[data_id] = df
                        logging.info(f"Dados carregados para dataId: {data_id}")
                except Exception as e:
                    logging.error(f"Erro ao ler dados {data_id}: {e}")
            else:
                logging.warning(f"Arquivo de dados {data_id} referenciado na config não encontrado.")

        if not datasets:
             return HTMLResponse("Nenhum arquivo de dados encontrado para este mapa.", status_code=404)

        # 3. Cria o mapa passando o dicionário de datasets
        # A função create_kepler_map em lib/map_utils.py agora aceita dict
        kepler_html = create_kepler_map(datasets, config)
        
        if isinstance(kepler_html, (bytes, bytearray)):
            kepler_html = kepler_html.decode("utf-8")

        map_label = config.get("label", f"Mapa {map_id}")
        kepler_html = normalize_kepler_html(kepler_html, map_label)

        return HTMLResponse(content=kepler_html, status_code=200)
    except Exception as e:
        logging.error(f"Erro ao renderizar o mapa '{map_id}': {e}", exc_info=True)
        return HTMLResponse(f"Erro ao renderizar o mapa: {e}", status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

import json
import logging
from keplergl import KeplerGl
import geopandas as gpd
import pandas as pd
from lib.convert_numpy import convert_numpy_types  
from data.load_data import read_geojsons  

# Set up logging
logging.basicConfig(level=logging.INFO)

def get_dataId_from_config(config):
    """
    Extrai a lista de dataIds necessários a partir do JSON de configuração.
    Isso permite saber quais arquivos buscar no disco.
    """
    if config is None:
        return []
    data_ids = []
    
    # Tenta acessar a raiz 'config' ou usa o objeto direto
    root_cfg = config.get("config", config)
    
    layers = root_cfg.get("visState", {}).get("layers", [])
    for layer in layers:
        data_id = layer.get("config", {}).get("dataId")
        if data_id:
            data_ids.append(data_id)
    return data_ids

def load_data(directory):
    try:
        geojson_data = read_geojsons(directory)
        return geojson_data
    except Exception as e:
        logging.error(f"Error loading data from directory {directory}: {e}")
        return None

def create_kepler_map(data_inputs, config, csv_data=None, additional_data=None):
    """
    Gera o HTML do mapa KeplerGL.
    
    Args:
        data_inputs: Pode ser um dicionário {'dataId': dataframe} (NOVO PADRÃO) 
                     ou um objeto de dados único (LEGADO).
        config: Dicionário de configuração do Kepler.
        csv_data, additional_data: Argumentos legados (mantidos para compatibilidade).
    """
    try:
        kepler_data = {}

        # --- Lógica 1: Input é um Dicionário (Suporte a Polígonos + KNN) ---
        if isinstance(data_inputs, dict):
            logging.info(f"Gerando mapa com {len(data_inputs)} datasets: {list(data_inputs.keys())}")
            for data_id, dataset in data_inputs.items():
                # Converte tipos numpy (int64, float32) para nativos python para evitar erros de JSON
                kepler_data[data_id] = convert_numpy_types(dataset)

        # --- Lógica 2: Input é único (Fallback/Legado) ---
        else:
            logging.info("Gerando mapa em modo legado (dataset único).")
            # Tenta descobrir o ID esperado pela config
            target_ids = get_dataId_from_config(config)
            
            # Mapeia o primeiro argumento
            if data_inputs is not None:
                primary_id = target_ids[0] if target_ids else "data_1"
                kepler_data[primary_id] = convert_numpy_types(data_inputs)
            
            # Mapeia o argumento csv_data se existir
            if csv_data is not None and len(target_ids) > 1:
                kepler_data[target_ids[1]] = convert_numpy_types(csv_data)

        # Cria a instância do KeplerGL
        # height=650 garante que o mapa ocupe bem o espaço no iframe
        kepler_map = KeplerGl(config=config, data=kepler_data, height=650)
        
        logging.info("KeplerGL map created successfully.")
        return kepler_map._repr_html_()

    except Exception as e:
        logging.error(f"Failed to create the KeplerGL map: {e}", exc_info=True)
        raise
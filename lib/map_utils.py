import json
import logging
from keplergl import KeplerGl
import geopandas as gpd
import pandas as pd
from lib.convert_numpy import convert_numpy_types  
from data.load_data import read_geojsons  

def get_dataId_from_config(config):
    if config is None:
        return []
    data_ids = []
    layers = config.get("config", {}).get("visState", {}).get("layers", [])
    for layer in layers:
        data_id = layer.get("config", {}).get("dataId")
        if data_id:
            data_ids.append(data_id)
    return data_ids

# Set up logging
logging.basicConfig(level=logging.INFO)

def load_data(directory):
    try:
        geojson_data = read_geojsons(directory)
        return geojson_data
    except Exception as e:
        logging.error(f"Error loading data from directory {directory}: {e}")
        return None

def create_kepler_map(geojson_data, config, csv_data=None, additional_data=None):
    try:
        kepler_data = {}
        data_ids = get_dataId_from_config(config)

        # Ensure that additional_data is a valid list
        if additional_data is None:
            additional_data = []

        # Process the layers according to their IDs
        for i, data_id in enumerate(data_ids):
            if "geojson" in data_id and geojson_data is not None:
                logging.info(f"Loading GeoJSON layer for {data_id}")
                kepler_data[data_id] = convert_numpy_types(geojson_data)
            elif "csv" in data_id and csv_data is not None:
                logging.info(f"Loading CSV layer for {data_id}")
                kepler_data[data_id] = convert_numpy_types(csv_data)
            elif i >= 2 and i - 2 < len(additional_data):
                logging.info(f"Loading additional layer for {data_id}")
                kepler_data[data_id] = convert_numpy_types(additional_data[i - 2])
            else:
                logging.warning(f"Data not found for dataId {data_id}")

        # Create the KeplerGL map with the processed layers
        kepler_map = KeplerGl(config=config, data=kepler_data)
        logging.info("KeplerGL map created successfully.")
        return kepler_map._repr_html_()

    except Exception as e:
        logging.error(f"Failed to create the KeplerGL map: {e}")
        raise

import os
import geopandas as gpd
import pandas as pd
import logging

# Configures logging to display information about loaded files or errors.
logging.basicConfig(level=logging.INFO)

def read_geojsons(*directories):
    """
    Reads all .geojson and .csv files from a list of directories.

    Args:
        *directories: A sequence of directory paths to search.

    Returns:
        A dictionary where the keys are the filenames and the values
        are the loaded data as GeoDataFrames (for .geojson) or
        DataFrames (for .csv).
    """
    datasets = {}
    for directory in directories:
        # Skips directories that do not exist to avoid errors.
        if not os.path.exists(directory):
            logging.warning(f"Directory not found, skipping: {directory}")
            continue
            
        logging.info(f"Reading files from directory: {directory}")
        for file in os.listdir(directory):
            file_path = os.path.join(directory, file)
            
            # Checks if it is a file before trying to read it.
            if not os.path.isfile(file_path):
                continue

            # Loads .geojson files
            if file.lower().endswith('.geojson'):
                try:
                    datasets[file] = gpd.read_file(file_path)
                    logging.info(f"GeoJSON file loaded successfully: {file_path}")
                except Exception as e:
                    logging.error(f"Error reading GeoJSON file {file_path}: {e}")
            
            # Loads .csv files
            elif file.lower().endswith('.csv'):
                try:
                    datasets[file] = pd.read_csv(file_path)
                    logging.info(f"CSV file loaded successfully: {file_path}")
                except Exception as e:
                    logging.error(f"Error reading CSV file {file_path}: {e}")
                    
    return datasets

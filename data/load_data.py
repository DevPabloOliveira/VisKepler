import os
import geopandas as gpd
import pandas as pd
import logging

# Configura o logging para exibir informações sobre os arquivos carregados ou erros.
logging.basicConfig(level=logging.INFO)

def read_geojsons(*directories):
    """
    Lê todos os arquivos .geojson e .csv de uma lista de diretórios.

    Args:
        *directories: Uma sequência de caminhos de diretório para pesquisar.

    Returns:
        Um dicionário onde as chaves são os nomes dos arquivos e os valores
        são os dados carregados como GeoDataFrames (para .geojson) ou
        DataFrames (para .csv).
    """
    datasets = {}
    for directory in directories:
        # Pula diretórios que não existem para evitar erros.
        if not os.path.exists(directory):
            logging.warning(f"O diretório não foi encontrado, pulando: {directory}")
            continue
            
        logging.info(f"Lendo arquivos do diretório: {directory}")
        for file in os.listdir(directory):
            file_path = os.path.join(directory, file)
            
            # Verifica se é um arquivo antes de tentar ler
            if not os.path.isfile(file_path):
                continue

            # Carrega arquivos .geojson
            if file.lower().endswith('.geojson'):
                try:
                    datasets[file] = gpd.read_file(file_path)
                    logging.info(f"Arquivo GeoJSON carregado com sucesso: {file_path}")
                except Exception as e:
                    logging.error(f"Erro ao ler o arquivo GeoJSON {file_path}: {e}")
            
            # Carrega arquivos .csv
            elif file.lower().endswith('.csv'):
                try:
                    datasets[file] = pd.read_csv(file_path)
                    logging.info(f"Arquivo CSV carregado com sucesso: {file_path}")
                except Exception as e:
                    logging.error(f"Erro ao ler o arquivo CSV {file_path}: {e}")
                    
    return datasets


# VisKepler - A Generic Geospatial Data Visualization Dashboard

This project provides a framework for analyzing and visualizing geospatial data using KeplerGl and other data visualization libraries. Users can upload their own KeplerGl JSON configurations and GeoJSON files to create interactive dashboards.

## Libraries Used

- **KeplerGl:** Interactive geospatial visualization library.
- **Pandas:** Data manipulation and analysis library.
- **Geopandas:** For working with geospatial data.
- **Matplotlib:** Static visualizations.
- **Seaborn:** Data visualization library based on Matplotlib.
- **FastAPI:** For creating the web application to serve the dashboard.

## About

This project originated from the **GETIN** project at Universidade de Aveiro, focusing on demographic data. It has been refactored to support generic use cases, allowing users to deploy their own data and visualizations.

Check live examples:
[Portuguese Demographic Data](https://dcspt-getin.ua.pt/kepler-pt-demo/)

## Instructions

1. **Deploy-ready version**:
   Contains the fastapi server, ready to be served under a reverse-proxy (like caddy or nginx)
   ```shell
   docker pull fillipefeitosa/viskepler:latest
   ```
2. **Development:**
   We recomend using conda, mamba or micromamba

   ```shell
   mamba env create -f environment.yml
   mamba activate viskepler
   uvicorn --host 0.0.0.0 --port 8050 --reload main:app
   ```

3. To contribute:
   New libs versions must come without hash
   ```shell
   conda env export --no-builds > environment.yml
   ```

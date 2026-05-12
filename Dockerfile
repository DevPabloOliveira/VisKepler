FROM continuumio/miniconda3

WORKDIR /app

ENV CONDA_NO_PLUGINS=true

COPY environment.yml .

# We removed the extra pip install here, as it's now handled by Conda
RUN conda config --set solver classic \
    && conda clean --all -y \
    && conda env update -n base -f environment.yml

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
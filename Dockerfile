FROM continuumio/miniconda3

WORKDIR /app

COPY environment.yml .

RUN conda env update -n base -f environment.yml

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

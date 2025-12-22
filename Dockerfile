FROM continuumio/miniconda3

WORKDIR /app

COPY environment.yml .

# CORREÇÃO: Instala as dependências diretamente no ambiente 'base'
RUN conda env update -n base -f environment.yml

COPY . .

EXPOSE 8000

# CORREÇÃO: Executa o uvicorn diretamente, sem ativar ambientes
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
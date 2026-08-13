FROM python:3.11-slim

# Establecer directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema necesarias para fpdf2 y compilaciones
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Crear un usuario y grupo no privilegiados con ID 10001
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -m -s /bin/bash appuser

# Copiar requirements e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo el código fuente con el propietario adecuado
COPY --chown=appuser:appgroup . .

# Asegurarse de que el directorio /app pertenece al usuario no privilegiado
RUN chown -R appuser:appgroup /app

# Exponer el puerto
EXPOSE 8050

# Usar el usuario no privilegiado
USER appuser

# Comando para ejecutar la aplicación
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8050"]

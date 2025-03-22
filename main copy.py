from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import sqlite3
import os
import json
import logging
from typing import List, Optional, Dict, Any

from logic import ReasoningSystem


import uvicorn

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("water_flow_api")

# Importar el sistema de razonamiento (asumimos que está en un archivo separado)

# Inicializar FastAPI
app = FastAPI(title="Sistema de Monitoreo de Flujo de Agua")

# Configurar CORS para permitir peticiones desde el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, restringir a dominios específicos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Modelo para los datos recibidos del ESP32
class FlujoAgua(BaseModel):
    flujo: float


# Modelo para análisis de tendencias
class TendenciaAnalisis(BaseModel):
    periodo: str
    tendencia: str
    recomendacion: str
    probabilidad_fuga: float


# Modelo para respuesta de historial
class RegistroFlujo(BaseModel):
    id: int
    flujo: float
    timestamp: str
    analisis: Optional[str] = None


# Clase para gestionar la base de datos
class DatabaseManager:
    def __init__(self, db_path="water_flow.db"):
        self.db_path = db_path
        self.initialize_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def initialize_db(self):
        """Crea las tablas necesarias si no existen"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Tabla para registros de flujo
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS flujo_registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flujo REAL NOT NULL,
            timestamp TEXT NOT NULL,
            analisis TEXT
        )
        """)

        # Tabla para análisis de tendencias
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tendencias_analisis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            periodo TEXT NOT NULL,
            tendencia TEXT NOT NULL,
            recomendacion TEXT NOT NULL,
            probabilidad_fuga REAL,
            detalles TEXT
        )
        """)

        # Tabla para configuración del sistema
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sistema_config (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        )
        """)

        # Insertar configuración por defecto si no existe
        cursor.execute("""
        INSERT OR IGNORE INTO sistema_config (clave, valor)
        VALUES ('umbral_alerta', '80.0')
        """)

        conn.commit()
        conn.close()
        logger.info("Base de datos inicializada correctamente")

    def guardar_flujo(self, flujo: float, analisis: str = None):
        """Guarda un nuevo registro de flujo en la base de datos"""
        conn = self.get_connection()
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()

        cursor.execute(
            "INSERT INTO flujo_registros (flujo, timestamp, analisis) VALUES (?, ?, ?)",
            (flujo, timestamp, analisis),
        )
        conn.commit()
        id_registro = cursor.lastrowid
        conn.close()

        return {
            "id": id_registro,
            "flujo": flujo,
            "timestamp": timestamp,
            "analisis": analisis,
        }

    def obtener_historial(self, limite: int = 100, offset: int = 0):
        """Obtiene el historial de registros de flujo"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, flujo, timestamp, analisis FROM flujo_registros ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limite, offset),
        )
        registros = cursor.fetchall()
        conn.close()

        return [
            {"id": reg[0], "flujo": reg[1], "timestamp": reg[2], "analisis": reg[3]}
            for reg in registros
        ]

    def obtener_estadisticas(self):
        """Obtiene estadísticas básicas de los datos de flujo"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Flujo promedio de las últimas 24 horas
        cursor.execute("""
            SELECT AVG(flujo) FROM flujo_registros 
            WHERE timestamp >= datetime('now', '-1 day')
        """)
        flujo_promedio_24h = cursor.fetchone()[0] or 0

        # Flujo máximo de las últimas 24 horas
        cursor.execute("""
            SELECT MAX(flujo) FROM flujo_registros 
            WHERE timestamp >= datetime('now', '-1 day')
        """)
        flujo_maximo_24h = cursor.fetchone()[0] or 0

        # Eficiencia: calculada como (flujo promedio / flujo máximo) * 100
        eficiencia = (
            (flujo_promedio_24h / flujo_maximo_24h * 100) if flujo_maximo_24h > 0 else 0
        )

        # Registros por hora (últimas 24 horas)
        cursor.execute("""
            SELECT strftime('%Y-%m-%d %H:00', timestamp) as hora, AVG(flujo) as promedio
            FROM flujo_registros
            WHERE timestamp >= datetime('now', '-1 day')
            GROUP BY hora
            ORDER BY hora
        """)
        registros_por_hora = cursor.fetchall()

        conn.close()

        return {
            "flujo_promedio_24h": round(flujo_promedio_24h, 2),
            "flujo_maximo_24h": round(flujo_maximo_24h, 2),
            "eficiencia": round(eficiencia, 2),
            "registros_por_hora": [
                {"hora": reg[0], "promedio": round(reg[1], 2)}
                for reg in registros_por_hora
            ],
        }

    def guardar_analisis_tendencia(self, analisis: Dict):
        """Guarda un análisis de tendencia generado por Gemini"""
        conn = self.get_connection()
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()

        cursor.execute(
            """
            INSERT INTO tendencias_analisis
            (fecha, periodo, tendencia, recomendacion, probabilidad_fuga, detalles)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                analisis.get("periodo", "24h"),
                analisis.get("tendencia", ""),
                analisis.get("recomendacion", ""),
                analisis.get("probabilidad_fuga", 0.0),
                json.dumps(analisis.get("detalles", {})),
            ),
        )
        conn.commit()
        conn.close()

    def obtener_ultimas_tendencias(self, limite: int = 5):
        """Obtiene los análisis de tendencias más recientes"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT fecha, periodo, tendencia, recomendacion, probabilidad_fuga, detalles
            FROM tendencias_analisis
            ORDER BY fecha DESC
            LIMIT ?
            """,
            (limite,),
        )
        tendencias = cursor.fetchall()
        conn.close()

        return [
            {
                "fecha": t[0],
                "periodo": t[1],
                "tendencia": t[2],
                "recomendacion": t[3],
                "probabilidad_fuga": t[4],
                "detalles": json.loads(t[5]) if t[5] else {},
            }
            for t in tendencias
        ]


# Inicializar gestor de base de datos
db_manager = DatabaseManager()

# Inicializar sistema de razonamiento
load_dotenv(".env")
API_KEY = os.getenv("GEMINI")
reasoning_system = ReasoningSystem(API_KEY)


# Función para analizar datos con Gemini en segundo plano
async def analizar_datos_flujo(ultimos_registros):
    """Analiza los datos de flujo utilizando Gemini"""
    if not ultimos_registros:
        return

    # Crear un prompt para Gemini basado en los datos
    flujos_recientes = [reg["flujo"] for reg in ultimos_registros]
    timestamps = [reg["timestamp"] for reg in ultimos_registros]

    query = f"""
    Analiza los siguientes datos de flujo de agua y proporciona una evaluación:
    
    Datos: {flujos_recientes}
    Timestamps: {timestamps}
    
    Proporciona:
    1. La tendencia general del flujo (estable, creciente, decreciente, fluctuante)
    2. Si hay indicios de posibles fugas basados en patrones anormales
    3. Una estimación de probabilidad de fuga (0-100%)
    4. Recomendaciones específicas basadas en estos datos
    
    Responde en formato JSON con las siguientes claves:
    tendencia, probabilidad_fuga, recomendacion, detalles
    """

    try:
        # Usar el sistema de razonamiento para analizar
        resultado = reasoning_system.generate_reasoned_response(query, num_cycles=2)

        # Intentar extraer el JSON de la respuesta
        import re

        json_match = re.search(r"\{.*\}", resultado, re.DOTALL)

        if json_match:
            analisis = json.loads(json_match.group(0))

            # Agregar periodo analizado
            analisis["periodo"] = (
                "últimas 24 horas"
                if len(ultimos_registros) > 24
                else f"últimos {len(ultimos_registros)} registros"
            )

            # Guardar el análisis en la base de datos
            db_manager.guardar_analisis_tendencia(analisis)
            logger.info(f"Análisis completado y guardado: {analisis}")
            return analisis
        else:
            logger.error(
                f"No se pudo extraer JSON de la respuesta de Gemini: {resultado}"
            )
            return None

    except Exception as e:
        logger.error(f"Error al analizar datos con Gemini: {str(e)}")
        return None


# Endpoints de la API


@app.post("/flujo")
async def recibir_flujo(data: FlujoAgua, background_tasks: BackgroundTasks):
    """Endpoint para recibir datos de flujo del ESP32"""
    logger.info(f"Flujo de agua recibido: {data.flujo}%")

    # Guardar el flujo en la base de datos
    registro = db_manager.guardar_flujo(data.flujo)

    # Obtener últimos registros para análisis (si hay suficientes)
    ultimos_registros = db_manager.obtener_historial(limite=48)
    if len(ultimos_registros) >= 100:  # Solo analizar si tenemos suficientes datos
        background_tasks.add_task(analizar_datos_flujo, ultimos_registros)

    return {
        "mensaje": "Flujo recibido correctamente",
        "flujo": data.flujo,
        "id_registro": registro["id"],
    }


@app.get("/historial", response_model=List[RegistroFlujo])
async def obtener_historial(limite: int = 100, offset: int = 0):
    """Obtiene el historial de registros de flujo"""
    registros = db_manager.obtener_historial(limite, offset)
    return registros


@app.get("/estadisticas")
async def obtener_estadisticas():
    """Obtiene estadísticas calculadas de los datos de flujo"""
    return db_manager.obtener_estadisticas()


@app.get("/tendencias")
async def obtener_tendencias(limite: int = 5):
    """Obtiene los análisis de tendencias más recientes"""
    return db_manager.obtener_ultimas_tendencias(limite)


@app.get("/analizar-ahora")
async def analizar_ahora(background_tasks: BackgroundTasks):
    """Fuerza un análisis inmediato de los datos"""
    ultimos_registros = db_manager.obtener_historial(limite=48)
    if len(ultimos_registros) >= 10:
        background_tasks.add_task(analizar_datos_flujo, ultimos_registros)
        return {"mensaje": "Análisis iniciado en segundo plano"}
    else:
        return {
            "mensaje": "No hay suficientes datos para analizar",
            "registros_disponibles": len(ultimos_registros),
        }


@app.get("/")
async def root():
    """Endpoint raíz para verificar que la API está funcionando"""
    return {"mensaje": "API de Monitoreo de Flujo de Agua funcionando correctamente"}


# Ejecutar la aplicación si este archivo es el punto de entrada
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import json
import os
from dotenv import load_dotenv
from google import genai

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("water_flow_api")

# Cargar variables de entorno
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI")

app = FastAPI(title="Sistema de Monitoreo de Flujo de Agua")

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Modelos para la API
class FlujoAgua(BaseModel):
    flujo: float


class RegistroFlujo(BaseModel):
    id: int
    flujo: float
    timestamp: str
    analisis: Optional[str] = None


class TendenciaAnalisis(BaseModel):
    id: Optional[int] = None
    fecha: str
    periodo: str
    tendencia: str
    recomendacion: str
    probabilidad_fuga: float
    detalles: Dict[str, Any] = {}


# Sistema de Razonamiento con Gemini
class ReasoningSystem:
    def __init__(self, api_key, model="gemini-1.5-pro"):
        """Inicializa el sistema de razonamiento con Gemini."""
        self.api_key = api_key
        self.model = model
        if api_key:
            self.client = genai.Client(api_key=api_key)
        else:
            logger.warning(
                "No se proporcionó API key para Gemini - El análisis no funcionará"
            )
            self.client = None

    def generate_reasoned_response(self, query, num_cycles=3, temperature=0.7):
        """Genera una respuesta utilizando ciclos de razonamiento."""
        if not self.client:
            return {
                "respuesta_final": "No se puede analizar: falta la API key de Gemini",
                "razonamiento": [{"ciclo": 1, "análisis": "No configurado"}],
            }

        try:
            prompt = self._create_prompt_for_flow_analysis(query, num_cycles)

            generation_config = {
                "temperature": temperature,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 4096,
            }

            response = self.client.models.generate_content(
                model=self.model, contents=prompt, config=generation_config
            )

            # Procesar respuesta para extraer JSON
            try:
                response_text = response.text.strip()
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1

                if json_start >= 0 and json_end > json_start:
                    json_text = response_text[json_start:json_end]
                    result = json.loads(json_text)

                    # Formatear resultado para el sistema de monitoreo
                    analisis = {
                        "tendencia": result.get("tendencia", "desconocida"),
                        "probabilidad_fuga": float(result.get("probabilidad_fuga", 0)),
                        "recomendacion": result.get(
                            "recomendacion", "No hay recomendaciones disponibles"
                        ),
                        "detalles": result.get("detalles", {}),
                    }
                    return analisis
                else:
                    # Fallback si no se encuentra JSON
                    return self._create_fallback_analysis(response_text)
            except Exception as e:
                logger.error(f"Error al procesar respuesta JSON: {e}")
                return self._create_fallback_analysis(response.text)

        except Exception as e:
            logger.error(f"Error en análisis Gemini: {e}")
            return {
                "tendencia": "error",
                "probabilidad_fuga": 0,
                "recomendacion": f"Error en análisis: {str(e)}",
                "detalles": {"error": str(e)},
            }

    def _create_prompt_for_flow_analysis(self, data, num_cycles=2):
        """Crea un prompt específico para análisis de datos de flujo."""
        return f"""
        # Análisis de Datos de Flujo de Agua
        
        Analiza los siguientes datos de flujo de agua y proporciona una evaluación detallada.
        
        ## Datos
        ```
        {data}
        ```
        
        ## Instrucciones
        Realiza un análisis completo siguiendo estos pasos:
        
        1. Identifica patrones en los datos de flujo (estables, ascendentes, descendentes, fluctuantes)
        2. Detecta anomalías que puedan indicar fugas o problemas
        3. Evalúa la probabilidad de una fuga basada en los patrones
        4. Proporciona recomendaciones específicas
        
        ## Formato de Respuesta
        Tu respuesta DEBE estar en formato JSON con exactamente esta estructura:
        
        {{
            "tendencia": "estable|creciente|decreciente|fluctuante",
            "probabilidad_fuga": valor_numérico_entre_0_y_100,
            "recomendacion": "texto con acción recomendada",
            "detalles": {{
                "patrones_identificados": ["lista", "de", "patrones"],
                "anomalias": ["lista", "de", "anomalías"],
                "explicacion": "explicación del análisis"
            }}
        }}
        """

    def _create_fallback_analysis(self, text):
        """Crea un análisis predeterminado si falla el procesamiento de JSON."""
        return {
            "tendencia": "análisis incompleto",
            "probabilidad_fuga": 0,
            "recomendacion": "Se recomienda revisar manualmente los datos",
            "detalles": {"respuesta_original": text[:500] + "..."},
        }


# Gestor de base de datos con funcionalidades ampliadas
class DatabaseManager:
    def __init__(self, db_path="water_flow.db"):
        self.db_path = db_path
        self.initialize_db()
        self.pending_analysis = False
        self.records_since_last_analysis = 0
        self.analysis_threshold = 5  # Analizar cada 5 registros

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def initialize_db(self):
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
        CREATE TABLE IF NOT EXISTS tendencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            periodo TEXT NOT NULL,
            tendencia TEXT NOT NULL,
            recomendacion TEXT NOT NULL,
            probabilidad_fuga REAL,
            detalles TEXT
        )
        """)

        # Tabla para estadísticas
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS estadisticas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            flujo_promedio REAL,
            flujo_maximo REAL,
            flujo_minimo REAL,
            eficiencia REAL
        )
        """)

        conn.commit()
        conn.close()
        logger.info("Base de datos inicializada correctamente")

    def guardar_flujo(self, flujo: float, analisis: str = None):
        """Guarda un registro de flujo y controla análisis automáticos."""
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

        # Incrementar contador para análisis automático
        self.records_since_last_analysis += 1

        # Determinar si es momento de hacer análisis
        if self.records_since_last_analysis >= self.analysis_threshold:
            self.pending_analysis = True
            logger.info(
                f"Se alcanzó umbral de {self.analysis_threshold} registros - Análisis pendiente"
            )

        return {
            "id": id_registro,
            "flujo": flujo,
            "timestamp": timestamp,
            "analisis": analisis,
            "pending_analysis": self.pending_analysis,
        }

    def obtener_historial(self, limite: int = 100, offset: int = 0):
        """Obtiene el historial de registros de flujo."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, flujo, timestamp, analisis 
            FROM flujo_registros 
            ORDER BY timestamp DESC 
            LIMIT ? OFFSET ?
            """,
            (limite, offset),
        )

        registros = cursor.fetchall()
        conn.close()

        return [
            {"id": reg[0], "flujo": reg[1], "timestamp": reg[2], "analisis": reg[3]}
            for reg in registros
        ]

    def obtener_estadisticas(self):
        """Obtiene estadísticas calculadas de los datos de flujo."""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Obtener estadísticas de las últimas 24 horas
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()

        # Flujo promedio
        cursor.execute(
            "SELECT AVG(flujo) FROM flujo_registros WHERE timestamp > ?", (yesterday,)
        )
        flujo_promedio = cursor.fetchone()[0] or 0

        # Flujo máximo
        cursor.execute(
            "SELECT MAX(flujo) FROM flujo_registros WHERE timestamp > ?", (yesterday,)
        )
        flujo_maximo = cursor.fetchone()[0] or 0

        # Flujo mínimo
        cursor.execute(
            "SELECT MIN(flujo) FROM flujo_registros WHERE timestamp > ?", (yesterday,)
        )
        flujo_minimo = cursor.fetchone()[0] or 0

        # Calcular eficiencia (lo simulamos como ejemplo)
        eficiencia = 95.0 if flujo_promedio > 0 else 0

        # Datos por hora (para gráficos)
        cursor.execute(
            """
            SELECT 
                strftime('%H', timestamp) as hora, 
                AVG(flujo) as promedio_flujo,
                COUNT(*) as total_registros
            FROM flujo_registros 
            WHERE timestamp > ?
            GROUP BY hora
            ORDER BY hora
        """,
            (yesterday,),
        )

        datos_por_hora = [
            {
                "hora": row[0],
                "promedio_flujo": round(row[1], 2),
                "total_registros": row[2],
            }
            for row in cursor.fetchall()
        ]

        # Contar total de registros
        cursor.execute("SELECT COUNT(*) FROM flujo_registros")
        total_registros = cursor.fetchone()[0]

        # Guardar estadísticas en la tabla
        current_timestamp = datetime.now().isoformat()
        cursor.execute(
            """
            INSERT INTO estadisticas 
            (fecha, flujo_promedio, flujo_maximo, flujo_minimo, eficiencia) 
            VALUES (?, ?, ?, ?, ?)
            """,
            (current_timestamp, flujo_promedio, flujo_maximo, flujo_minimo, eficiencia),
        )
        conn.commit()

        conn.close()

        return {
            "flujo_promedio": round(flujo_promedio, 2),
            "flujo_maximo": round(flujo_maximo, 2),
            "flujo_minimo": round(flujo_minimo, 2),
            "eficiencia": round(eficiencia, 2),
            "datos_por_hora": datos_por_hora,
            "total_registros": total_registros,
            "fecha_calculo": current_timestamp,
        }

    def guardar_analisis_tendencia(self, analisis):
        """Guarda un análisis de tendencia en la base de datos."""
        conn = self.get_connection()
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()

        cursor.execute(
            """
            INSERT INTO tendencias 
            (fecha, periodo, tendencia, recomendacion, probabilidad_fuga, detalles) 
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                analisis.get("periodo", "últimas 24 horas"),
                analisis.get("tendencia", "desconocida"),
                analisis.get("recomendacion", "No hay recomendaciones"),
                analisis.get("probabilidad_fuga", 0.0),
                json.dumps(analisis.get("detalles", {})),
            ),
        )

        conn.commit()
        id_analisis = cursor.lastrowid
        conn.close()

        # Resetear contador de análisis
        self.records_since_last_analysis = 0
        self.pending_analysis = False

        return id_analisis

    def obtener_ultimas_tendencias(self, limite: int = 5):
        """Obtiene los análisis de tendencias más recientes."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, fecha, periodo, tendencia, recomendacion, probabilidad_fuga, detalles
            FROM tendencias
            ORDER BY fecha DESC
            LIMIT ?
            """,
            (limite,),
        )

        tendencias = cursor.fetchall()
        conn.close()

        return [
            {
                "id": t[0],
                "fecha": t[1],
                "periodo": t[2],
                "tendencia": t[3],
                "recomendacion": t[4],
                "probabilidad_fuga": t[5],
                "detalles": json.loads(t[6]) if t[6] else {},
            }
            for t in tendencias
        ]

    def necesita_analisis(self):
        """Verifica si se debe realizar un análisis automático."""
        return self.pending_analysis


# Inicializar componentes
db_manager = DatabaseManager()
reasoning_system = ReasoningSystem(GEMINI_API_KEY)


# Función para analizar datos
async def analizar_datos_flujo():
    """Analiza los datos de flujo utilizando el sistema de razonamiento."""
    if not reasoning_system.client:
        logger.warning(
            "No se puede realizar análisis: sistema de razonamiento no inicializado"
        )
        return None

    # Obtener los últimos registros
    registros = db_manager.obtener_historial(limite=50)
    if len(registros) < 5:
        logger.warning("No hay suficientes datos para analizar")
        return None

    # Formatear datos para el análisis
    datos_formateados = "\n".join(
        [
            f"ID: {r['id']}, Flujo: {r['flujo']}%, Timestamp: {r['timestamp']}"
            for r in registros[:50]
        ]
    )

    # Calcular estadísticas básicas para el análisis
    flujos = [r["flujo"] for r in registros[:50]]
    stats = {
        "promedio": sum(flujos) / len(flujos) if flujos else 0,
        "maximo": max(flujos) if flujos else 0,
        "minimo": min(flujos) if flujos else 0,
        "total_registros": len(registros),
    }

    # Crear query para análisis
    query = f"""
    Análisis de datos de flujo de agua:
    
    Estadísticas:
    - Promedio: {stats["promedio"]:.2f}%
    - Máximo: {stats["maximo"]:.2f}%
    - Mínimo: {stats["minimo"]:.2f}%
    - Total registros: {stats["total_registros"]}
    
    Últimos 10 registros:
    {datos_formateados[:10]}
    """

    # Realizar análisis
    resultado = reasoning_system.generate_reasoned_response(query)

    # Guardar análisis en la base de datos
    if resultado:
        resultado["periodo"] = f"últimos {len(registros)} registros"
        id_analisis = db_manager.guardar_analisis_tendencia(resultado)
        logger.info(f"Análisis completado y guardado con ID: {id_analisis}")
        return resultado

    return None


# Endpoints


@app.post("/flujo")
async def recibir_flujo(
    data: FlujoAgua, request: Request, background_tasks: BackgroundTasks
):
    """Recibe datos de flujo desde el dispositivo ESP32."""
    client_host = request.client.host
    logger.info(f"Flujo recibido: {data.flujo}% desde {client_host}")

    # Guardar el flujo en la base de datos
    resultado = db_manager.guardar_flujo(data.flujo)

    # Verificar si es momento de analizar
    if db_manager.necesita_analisis():
        background_tasks.add_task(analizar_datos_flujo)
        logger.info("Análisis programado en segundo plano")

    return {
        "mensaje": "Flujo recibido correctamente",
        "flujo": data.flujo,
        "id_registro": resultado["id"],
        "timestamp": resultado["timestamp"],
    }


@app.get("/historial")
async def obtener_historial(limite: int = 100, offset: int = 0):
    """Obtiene el historial de registros de flujo."""
    registros = db_manager.obtener_historial(limite, offset)
    return registros


@app.get("/estadisticas")
async def obtener_estadisticas():
    """Obtiene estadísticas calculadas de los datos de flujo."""
    return db_manager.obtener_estadisticas()


@app.get("/tendencias")
async def obtener_tendencias(limite: int = 5):
    """Obtiene los análisis de tendencias más recientes."""
    return db_manager.obtener_ultimas_tendencias(limite)


@app.get("/analizar-ahora")
async def analizar_ahora(background_tasks: BackgroundTasks):
    """Fuerza un análisis inmediato de los datos."""
    background_tasks.add_task(analizar_datos_flujo)
    return {"mensaje": "Análisis iniciado en segundo plano"}


@app.get("/")
async def root():
    """Endpoint raíz para verificar que la API está funcionando."""
    return {
        "mensaje": "API de Monitoreo de Flujo de Agua funcionando correctamente",
        "endpoints": [
            {
                "ruta": "/flujo",
                "método": "POST",
                "descripción": "Recibir datos de flujo",
            },
            {
                "ruta": "/historial",
                "método": "GET",
                "descripción": "Obtener historial de datos",
            },
            {
                "ruta": "/estadisticas",
                "método": "GET",
                "descripción": "Obtener estadísticas",
            },
            {
                "ruta": "/tendencias",
                "método": "GET",
                "descripción": "Obtener análisis de tendencias",
            },
            {
                "ruta": "/analizar-ahora",
                "método": "GET",
                "descripción": "Forzar análisis de datos",
            },
        ],
        "version": "1.0.0",
    }


@app.get("/ultimos-datos", include_in_schema=False)
async def ultimos_datos(limit: int = 10):
    """Obtiene los últimos datos registrados (para compatibilidad)."""
    return db_manager.obtener_historial(limite=limit)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

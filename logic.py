from google import genai
import json
import time
import os
from dotenv import load_dotenv


class ReasoningSystem:
    def __init__(self, api_key, model="gemini-1.5-pro"):
        """
        Inicializa el sistema de razonamiento con Gemini.

        Args:
            api_key (str): API key de Google AI
            model (str): Modelo de Gemini a utilizar (por defecto: gemini-1.5-pro)
        """
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.history = []

    def _create_reasoning_prompt(self, query, num_cycles=3):
        """
        Crea un prompt estructurado para fomentar el razonamiento por ciclos.

        Args:
            query (str): La pregunta o instrucción del usuario
            num_cycles (int): Número de ciclos de razonamiento

        Returns:
            str: Prompt estructurado para Gemini
        """
        return f"""
        Actúa como un sistema de razonamiento avanzado que responde a consultas mediante ciclos de pensamiento.
        
        IMPORTANTE: DEBES devolver SOLO un objeto JSON válido con EXACTAMENTE esta estructura, sin texto adicional antes o después:
        
        {{
            "razonamiento": [
                {{
                    "ciclo": 1,
                    "análisis": "Tu análisis inicial...",
                    "ideas": "Ideas generadas...",
                    "evaluación": "Evaluación crítica...",
                    "refinamiento": "Refinamiento de la idea..."
                }},
                // Repite exactamente este formato para cada ciclo
            ],
            "respuesta_final": "Tu respuesta final en formato markdown, didáctica e incluyendo emojis apropiados."
        }}
        
        # Instrucción
        Responde a la siguiente consulta utilizando exactamente {num_cycles} ciclos de razonamiento explícito. 
        Para cada ciclo, debes:
        
        1. Analizar la información disponible hasta el momento
        2. Generar nuevas ideas o perspectivas
        3. Evaluar críticamente tus conclusiones
        4. Refinar tu respuesta basada en este análisis
        
        # Consulta
        {query}
        
        Recuerda: tu respuesta DEBE ser SOLO un objeto JSON válido que siga EXACTAMENTE la estructura solicitada.
        """

    def generate_reasoned_response(self, query, num_cycles=3, temperature=0.7):
        """
        Genera una respuesta utilizando ciclos de razonamiento.

        Args:
            query (str): La pregunta o instrucción del usuario
            num_cycles (int): Número de ciclos de razonamiento
            temperature (float): Nivel de creatividad (0.0-1.0)

        Returns:
            dict: Respuesta completa incluyendo ciclos de razonamiento y respuesta final
        """
        try:
            prompt = self._create_reasoning_prompt(query, num_cycles)

            # Configura parámetros de generación
            generation_config = {
                "temperature": temperature,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 4096,
            }

            # Registra el tiempo de inicio
            start_time = time.time()

            # Genera la respuesta
            response = self.client.models.generate_content(
                model=self.model, contents=prompt, config=generation_config
            )

            # Registra el tiempo de finalización
            elapsed_time = time.time() - start_time

            # Intenta parsear la respuesta como JSON
            try:
                # Primero limpiamos el texto para encontrar solo la parte JSON válida
                response_text = response.text.strip()

                # Buscar el inicio y fin de un posible objeto JSON
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1

                if json_start >= 0 and json_end > json_start:
                    # Extraer el texto que parece ser JSON
                    json_text = response_text[json_start:json_end]
                    # Intentar parsear
                    result = json.loads(json_text)
                else:
                    raise json.JSONDecodeError(
                        "No se encontró estructura JSON", response_text, 0
                    )

                # Verificar que contenga las claves esperadas
                if "razonamiento" not in result and "respuesta_final" not in result:
                    # Si no contiene las claves esperadas, construimos una estructura válida
                    processed_response = {
                        "razonamiento": [
                            {
                                "ciclo": 1,
                                "análisis": "Procesamiento directo sin ciclos explícitos",
                            }
                        ],
                        "respuesta_final": response.text
                        if "respuesta_final" not in result
                        else result["respuesta_final"],
                    }
                    result = processed_response

            except (json.JSONDecodeError, ValueError):
                # Si no es JSON válido, o falla por cualquier motivo, estructuramos manualmente
                result = {
                    "razonamiento": [
                        {
                            "ciclo": 1,
                            "análisis": "El modelo no estructuró la respuesta en el formato solicitado",
                        }
                    ],
                    "respuesta_final": response.text,
                    "formato_original": "texto_plano",
                }

            # Agrega metadatos
            result["metadatos"] = {
                "modelo": self.model,
                "tiempo_generacion": f"{elapsed_time:.2f} segundos",
                "ciclos_solicitados": num_cycles,
                "temperatura": temperature,
            }

            # Guarda en el historial
            self.history.append(
                {"query": query, "response": result, "timestamp": time.time()}
            )

            return result

        except Exception as e:
            return {
                "error": str(e),
                "respuesta_final": f"Error al generar respuesta: {str(e)}",
            }

    def stream_final_response(self, query, num_cycles=3, temperature=0.7):
        """
        Genera y transmite solo la respuesta final usando el streaming nativo de la API.

        Args:
            query (str): La pregunta o instrucción del usuario
            num_cycles (int): Número de ciclos de razonamiento (procesados internamente)
            temperature (float): Nivel de creatividad (0.0-1.0)

        Yields:
            str: Fragmentos de la respuesta final
        """
        try:
            # Creamos un prompt simplificado para streaming directo
            direct_prompt = f"""
            Responde a la siguiente consulta de manera didáctica, usando markdown y emojis apropiados:
            
            {query}
            
            Piensa paso a paso antes de responder, considerando al menos {num_cycles} perspectivas diferentes.
            """

            # Configura parámetros de generación
            generation_config = {
                "temperature": temperature,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 2048,
            }

            # Usamos el streaming nativo de la API
            response_stream = self.client.models.generate_content_stream(
                model=self.model,
                contents=direct_prompt,
                config=generation_config,
            )

            # Devolvemos los chunks tal como llegan
            for chunk in response_stream:
                if hasattr(chunk, "text") and chunk.text:
                    yield chunk.text

        except Exception as e:
            yield f"Error en streaming: {str(e)}"


# Ejemplo de uso
if __name__ == "__main__":
    # Cargar variables de entorno desde un archivo .env
    # Obtener la API key desde la variable de entorno
    load_dotenv(".env")
    API_KEY = os.getenv("GEMINI")

    # Crea una instancia del sistema
    reasoning_system = ReasoningSystem(api_key=API_KEY, model="gemini-2.0-flash-exp")

    # Ejemplo 1: Obtener respuesta completa con ciclos de razonamiento
    query = (
        "Explica cómo crear agentes con N8N y las mejores integraciones disponibles."
    )
    result = reasoning_system.generate_reasoned_response(query, num_cycles=3)

    # Imprimir la respuesta completa para depuración
    print("\n==== RESPUESTA COMPLETA (PARA DEPURACIÓN) ====")
    print(result)

    print("\n==== CICLOS DE RAZONAMIENTO ====")
    # Verificamos que exista la clave 'razonamiento' antes de iterar
    if "razonamiento" in result:
        for cycle in result["razonamiento"]:
            print(f"\nCICLO {cycle.get('ciclo', 'N/A')}:")

            # Usamos .get() para evitar KeyError si falta alguna clave
            print(f"Análisis: {cycle.get('análisis', 'No disponible')[:100]}...")
            print(f"Ideas: {cycle.get('ideas', 'No disponible')[:100]}...")
            print(f"Evaluación: {cycle.get('evaluación', 'No disponible')[:100]}...")
            print(
                f"Refinamiento: {cycle.get('refinamiento', 'No disponible')[:100]}..."
            )
    else:
        print("No se encontraron ciclos de razonamiento en la respuesta.")

    print("\n==== RESPUESTA FINAL ====")
    print(result.get("respuesta_final", "No se encontró respuesta final."))

    # Ejemplo 2: Streaming de solo la respuesta final
    print("\n==== STREAMING DE RESPUESTA ====")
    query = "¿Cuáles son los principios éticos más importantes en el desarrollo de IA?"

    for chunk in reasoning_system.stream_final_response(query, num_cycles=2):
        print(chunk, end="", flush=True)

    # Meterle las 4R de la IA o algo así

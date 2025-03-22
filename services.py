# Endpoints para el ESP32
@app.post("/api/sensor-data", response_model=dict)
async def receive_sensor_data(
    data: SensorData, db: sqlite3.Connection = Depends(get_db)
):
    """Recibe datos del sensor desde el ESP32"""
    if not data.timestamp:
        data.timestamp = datetime.datetime.now().isoformat()

    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO sensor_data (device_id, water_level, valve_status, timestamp) VALUES (?, ?, ?, ?)",
        (
            data.device_id,
            data.water_level,
            1 if data.valve_status else 0,
            data.timestamp,
        ),
    )

    # Actualizar estado del dispositivo
    cursor.execute(
        "INSERT OR REPLACE INTO device_status (device_id, online, last_seen) VALUES (?, 1, ?)",
        (data.device_id, datetime.datetime.now().isoformat()),
    )

    # Verificar si supera el umbral para crear una alerta
    cursor.execute(
        "SELECT alert_threshold FROM device_config WHERE device_id = ?",
        (data.device_id,),
    )
    config = cursor.fetchone()

    if config and data.water_level > config[0]:
        cursor.execute(
            "INSERT INTO alerts (device_id, message, level, timestamp) VALUES (?, ?, ?, ?)",
            (
                data.device_id,
                f"Nivel de agua crítico: {data.water_level}%",
                3,
                datetime.datetime.now().isoformat(),
            ),
        )

    db.commit()

    # Obtener la configuración actual para el dispositivo
    cursor.execute(
        "SELECT valve_auto_control, alert_threshold, reading_interval FROM device_config WHERE device_id = ?",
        (data.device_id,),
    )
    device_config = cursor.fetchone()

    if not device_config:
        # Crear configuración por defecto si no existe
        cursor.execute(
            "INSERT INTO device_config (device_id, valve_auto_control, alert_threshold, reading_interval) VALUES (?, ?, ?, ?)",
            (data.device_id, 1, 80.0, 30),
        )
        db.commit()
        valve_auto_control = 1
        alert_threshold = 80.0
        reading_interval = 30
    else:
        valve_auto_control = device_config[0]
        alert_threshold = device_config[1]
        reading_interval = device_config[2]

    # Retornar instrucciones al dispositivo
    return {
        "status": "success",
        "valve_command": "close"
        if (valve_auto_control and data.water_level > alert_threshold)
        else "no_change",
        "reading_interval": reading_interval,
        "server_time": datetime.datetime.now().isoformat(),
    }


@app.post("/api/alerts", response_model=dict)
async def create_alert(alert: AlertData, db: sqlite3.Connection = Depends(get_db)):
    """Permite al ESP32 enviar alertas al servidor"""
    if not alert.timestamp:
        alert.timestamp = datetime.datetime.now().isoformat()

    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO alerts (device_id, message, level, timestamp) VALUES (?, ?, ?, ?)",
        (alert.device_id, alert.message, alert.level, alert.timestamp),
    )
    db.commit()

    return {"status": "success", "alert_id": cursor.lastrowid}


@app.get("/api/config/{device_id}", response_model=DeviceConfig)
async def get_device_config(device_id: str, db: sqlite3.Connection = Depends(get_db)):
    """Permite al ESP32 obtener su configuración"""
    cursor = db.cursor()
    cursor.execute(
        "SELECT device_id, valve_auto_control, alert_threshold, reading_interval FROM device_config WHERE device_id = ?",
        (device_id,),
    )
    config = cursor.fetchone()

    if not config:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")

    return {
        "device_id": config[0],
        "valve_auto_control": bool(config[1]),
        "alert_threshold": config[2],
        "reading_interval": config[3],
    }


# Endpoints para el Frontend
@app.get("/api/sensor-data/{device_id}", response_model=List[dict])
async def get_sensor_data(
    device_id: str,
    limit: int = Query(50, ge=1, le=1000),
    db: sqlite3.Connection = Depends(get_db),
):
    """Obtiene los datos históricos de un sensor para mostrar en el frontend"""
    cursor = db.cursor()
    cursor.execute(
        """
        SELECT id, device_id, water_level, valve_status, timestamp 
        FROM sensor_data 
        WHERE device_id = ? 
        ORDER BY timestamp DESC 
        LIMIT ?
        """,
        (device_id, limit),
    )
    data = cursor.fetchall()

    return [
        {
            "id": row[0],
            "device_id": row[1],
            "water_level": row[2],
            "valve_status": bool(row[3]),
            "timestamp": row[4],
        }
        for row in data
    ]


@app.get("/api/alerts/{device_id}", response_model=List[dict])
async def get_alerts(
    device_id: str,
    limit: int = Query(50, ge=1, le=1000),
    db: sqlite3.Connection = Depends(get_db),
):
    """Obtiene las alertas para un dispositivo"""
    cursor = db.cursor()
    cursor.execute(
        """
        SELECT id, device_id, message, level, timestamp 
        FROM alerts 
        WHERE device_id = ? 
        ORDER BY timestamp DESC 
        LIMIT ?
        """,
        (device_id, limit),
    )
    alerts = cursor.fetchall()

    return [
        {
            "id": row[0],
            "device_id": row[1],
            "message": row[2],
            "level": row[3],
            "timestamp": row[4],
        }
        for row in alerts
    ]


@app.get("/api/devices", response_model=List[DeviceStatus])
async def get_all_devices(db: sqlite3.Connection = Depends(get_db)):
    """Obtiene una lista de todos los dispositivos registrados"""
    cursor = db.cursor()
    cursor.execute(
        "SELECT device_id, online, last_seen, battery, firmware_version FROM device_status"
    )
    devices = cursor.fetchall()

    return [
        {
            "device_id": row[0],
            "online": bool(row[1]),
            "last_seen": row[2],
            "battery": row[3],
            "firmware_version": row[4],
        }
        for row in devices
    ]


@app.put("/api/config/{device_id}", response_model=DeviceConfig)
async def update_device_config(
    device_id: str, config: DeviceConfig, db: sqlite3.Connection = Depends(get_db)
):
    """Actualiza la configuración de un dispositivo desde el frontend"""
    if device_id != config.device_id:
        raise HTTPException(status_code=400, detail="ID de dispositivo no coincide")

    cursor = db.cursor()
    cursor.execute(
        """
        UPDATE device_config 
        SET valve_auto_control = ?, alert_threshold = ?, reading_interval = ? 
        WHERE device_id = ?
        """,
        (
            1 if config.valve_auto_control else 0,
            config.alert_threshold,
            config.reading_interval,
            device_id,
        ),
    )

    if cursor.rowcount == 0:
        # Insertar si no existe
        cursor.execute(
            """
            INSERT INTO device_config (device_id, valve_auto_control, alert_threshold, reading_interval)
            VALUES (?, ?, ?, ?)
            """,
            (
                device_id,
                1 if config.valve_auto_control else 0,
                config.alert_threshold,
                config.reading_interval,
            ),
        )

    db.commit()

    return config


# Endpoint simulador para probar sin ESP32 real
@app.get("/api/simulator/generate-data")
async def generate_simulated_data(db: sqlite3.Connection = Depends(get_db)):
    """Genera datos simulados de sensor como si vinieran del ESP32"""
    # Obtener todos los dispositivos configurados
    cursor = db.cursor()
    cursor.execute("SELECT device_id FROM device_config")
    devices = cursor.fetchall()

    if not devices:
        # Si no hay dispositivos, usar uno demo
        devices = [("ESP32_DEMO",)]

    results = []

    for device in devices:
        device_id = device[0]

        # Generar datos simulados
        water_level = random.uniform(
            10.0, 95.0
        )  # Nivel de agua aleatorio entre 10% y 95%
        valve_status = water_level > 85.0  # Cerrar válvula si nivel > 85%

        # Crear entrada simulada
        data = SensorData(
            device_id=device_id,
            water_level=water_level,
            valve_status=not valve_status,  # True = abierta, False = cerrada
            timestamp=datetime.datetime.now().isoformat(),
        )

        # Usar el endpoint existente para procesar los datos simulados
        result = await receive_sensor_data(data, db)
        results.append(
            {
                "device_id": device_id,
                "simulated_data": {
                    "water_level": water_level,
                    "valve_status": not valve_status,
                },
                "server_response": result,
            }
        )

    return {"simulation_results": results}

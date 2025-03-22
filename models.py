
# Modelos de datos
class SensorData(BaseModel):
    device_id: str
    water_level: float
    valve_status: bool
    timestamp: Optional[str] = None


class AlertData(BaseModel):
    device_id: str
    message: str
    level: int  # 1: Informativo, 2: Advertencia, 3: Crítico
    timestamp: Optional[str] = None


class DeviceConfig(BaseModel):
    device_id: str
    valve_auto_control: bool
    alert_threshold: float
    reading_interval: int  # segundos


class DeviceStatus(BaseModel):
    device_id: str
    online: bool
    last_seen: str
    battery: Optional[float] = None
    firmware_version: Optional[str] = None

SALE_CAT_SELECTION = [
    ('A', 'A — Alta rotación'),
    ('B', 'B'),
    ('C', 'C'),
    ('D', 'D'),
    ('E', 'E — Baja rotación'),
]

DEFAULT_PO_CRITICAL_DAYS = 5

# Umbrales de semáforo para análisis de proveedores (% entregas a tiempo)
DEFAULT_ON_TIME_GREEN_PCT = 90
DEFAULT_ON_TIME_YELLOW_PCT = 70

# Días sin compra a partir del cual un cliente/proveedor se considera en riesgo
DEFAULT_RISK_DAYS = 90

# Días sin rotación a partir del cual se emite alerta de quiebre de stock
DEFAULT_ROTATION_WARN_DAYS = 90

# Umbrales de cobertura de forecast (% respecto al demand objetivo)
FORECAST_WARNING_PCT = 70
FORECAST_CRITICAL_PCT = 50

# Límites de recencia para scoring RFM (días desde última compra)
RFM_RECENCY_RECENT_DAYS = 30
RFM_RECENCY_MEDIUM_DAYS = 90
